"""POST /api/generate-diagnostic — Submit a diagnostic assessment generation job.

Receives { courseId }.
Loads the skill tree from KV, parses the mermaid chart to understand
the prerequisite structure, builds a comprehensive Claude prompt
following psychometric best practices, and submits to the Anthropic
Batch API.
"""

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import send_json
from api._kv import kv_get, kv_set, kv_delete

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BATCH_URL = "https://api.anthropic.com/v1/messages/batches"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-opus-4-6"


def _anthropic_headers():
    return {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _parse_mermaid_structure(mermaid_code: str) -> dict:
    """Parse a mermaid flowchart into nodes, edges, and subgraphs."""
    nodes = {}
    edges = []
    subgraphs = {}

    # Extract nodes: U1S1["Label here"]
    for m in re.finditer(r'(\w+)\["([^"]+)"\]', mermaid_code):
        nid, label = m.group(1), m.group(2)
        if nid not in nodes:
            nodes[nid] = label

    # Extract edges: A --> B
    for m in re.finditer(r'(\w+)\s*-->\s*(\w+)', mermaid_code):
        src, tgt = m.group(1), m.group(2)
        if src in nodes and tgt in nodes:
            edges.append((src, tgt))

    # Extract subgraphs: subgraph U1["Unit 1: Topic Name"]
    for m in re.finditer(r'subgraph\s+(\w+)\["([^"]+)"\]', mermaid_code):
        sg_id, sg_label = m.group(1), m.group(2)
        subgraphs[sg_id] = sg_label

    return {
        "nodes": nodes,
        "edges": edges,
        "subgraphs": subgraphs,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "subgraph_count": len(subgraphs),
    }


def _filter_mermaid_by_units(mermaid_code: str, selected_units: list[str]) -> str:
    """Filter mermaid code to only include the specified subgraph blocks.

    Extracts the 'graph TD' header and the subgraph...end blocks whose
    IDs are in selected_units.  Also keeps any cross-unit edges that
    connect nodes within the selected subgraphs.
    """
    selected = set(selected_units)
    lines = mermaid_code.split("\n")
    result = []
    inside_subgraph = False
    current_sg_id = None
    keep = False

    for line in lines:
        stripped = line.strip()

        # Keep the graph header
        if stripped.startswith("graph ") or stripped.startswith("flowchart "):
            result.append(line)
            continue

        # Detect subgraph start
        sg_match = re.match(r'subgraph\s+(\w+)', stripped)
        if sg_match:
            current_sg_id = sg_match.group(1)
            inside_subgraph = True
            keep = current_sg_id in selected
            if keep:
                result.append(line)
            continue

        # Detect subgraph end
        if stripped == "end":
            if inside_subgraph and keep:
                result.append(line)
            inside_subgraph = False
            current_sg_id = None
            keep = False
            continue

        # Inside a subgraph — keep if selected
        if inside_subgraph:
            if keep:
                result.append(line)
            continue

        # Outside any subgraph — cross-unit edges
        # Keep edges where both nodes belong to selected units
        edge_match = re.match(r'\s*(\w+)\s*-->\s*(\w+)', stripped)
        if edge_match:
            src, tgt = edge_match.group(1), edge_match.group(2)
            # Check if node IDs start with any selected unit prefix
            src_ok = any(src.startswith(uid) for uid in selected)
            tgt_ok = any(tgt.startswith(uid) for uid in selected)
            if src_ok and tgt_ok:
                result.append(line)
            continue

        # Keep blank lines / comments
        if not stripped:
            result.append(line)

    return "\n".join(result)


def _needs_stimulus(course_title: str) -> bool:
    """Detect if a course likely needs passage/stimulus-based questions."""
    t = (course_title or "").lower()
    stimulus_keywords = [
        "lang", "literature", "lit", "english", "reading",
        "history", "world", "european", "us hist", "u.s. hist",
        "government", "politics", "seminar", "research",
    ]
    return any(kw in t for kw in stimulus_keywords)


def _build_prompt(course_title: str, mermaid_code: str, structure: dict) -> tuple[str, str]:
    """Build the system and user messages for diagnostic generation."""

    needs_stim = _needs_stimulus(course_title)
    node_count = structure["node_count"]
    # Target ~50 items, but scale with tree size
    target_items = min(60, max(30, node_count // 8))

    system_msg = (
        "You are an expert psychometrician, instructional designer, and AP curriculum "
        "specialist. You create placement/diagnostic assessments that reliably measure "
        "student mastery across a skill tree. You follow classical test theory and "
        "evidence-based item construction principles."
    )

    stimulus_instruction = ""
    if needs_stim:
        stimulus_instruction = """
STIMULUS/PASSAGE GENERATION:
This course requires passage-based questions. For items that test reading
comprehension, analysis, or argumentation skills:
- Generate a SHORT passage (150-300 words) as the "stimulus" field
- The passage should be grade-appropriate and relevant to the skill being tested
- Multiple items CAN share the same stimulus (group them with the same stimulusGroup ID)
- Not every item needs a stimulus — factual recall items can omit it
- For history courses: use primary source excerpts (you may create realistic ones)
- For language/literature courses: use literary passages, rhetorical texts, or argumentative essays
"""

    user_msg = f"""Create a comprehensive diagnostic/placement assessment for this AP course.

**Course**: {course_title}
**Skill Tree** ({node_count} nodes, {structure['edge_count']} prerequisite edges, {structure['subgraph_count']} units):

```
{mermaid_code}
```

**YOUR TASK** — Complete these steps IN ORDER, then output structured JSON:

## Step 1: Identify Gateway Nodes (~{target_items} nodes)
Analyze the skill tree and identify the most critical "gateway nodes" for placement.
A gateway node is one that:
- Gates access to multiple downstream skills (high fan-out)
- Represents a meaningful placement boundary
- Is a common prerequisite failure point
- Sits at a key depth level in the tree

Select ~{target_items} gateway nodes distributed across ALL units/subgraphs.

## Step 2: Assign Difficulty Targets
Distribute difficulties so the AVERAGE p-value ≈ 0.50:
- Easy anchors (p = 0.80–0.95): ~15% of items — confirm foundational skills
- Moderate-easy (p = 0.60–0.79): ~20% of items
- Target sweet spot (p = 0.40–0.59): ~30% of items — maximum discrimination
- Moderate-hard (p = 0.21–0.39): ~20% of items
- Hard ceiling (p = 0.05–0.20): ~15% of items — identify advanced students

## Step 3: Generate Assessment Items
For each gateway node, create ONE 4-option multiple-choice item:
- The stem must be clear, concise, and test ONE skill
- The correct answer must be unambiguously correct
- All 3 distractors must be plausible, each targeting a SPECIFIC misconception
- Distractors should be similar length to the correct answer
- No "all of the above" or "none of the above"
- No negative phrasing ("Which is NOT...")
- At least 30% of items at Apply or Analyze level (Bloom's taxonomy)
{stimulus_instruction}
## Step 4: Create Test Blueprint
Map items to a domain × Bloom's level matrix showing coverage.

## Step 5: Define Cut Scores
Using the prerequisite chain depths, define placement levels with cut scores.
Place students at the highest level where they demonstrate ≥ 80% mastery.

**OUTPUT FORMAT — Return ONLY valid JSON, no other text:**
{{
  "gatewayNodes": [
    {{
      "id": "<nodeId from tree>",
      "label": "<skill label>",
      "depth": <integer depth in tree>,
      "targetDifficulty": <p-value 0.05-0.95>,
      "reason": "<why this is a gateway node>"
    }}
  ],
  "items": [
    {{
      "id": "item_<number>",
      "gatewayNodeId": "<nodeId>",
      "gatewayNodeLabel": "<skill label>",
      "targetDifficulty": <p-value>,
      "bloomsLevel": "<Remember|Understand|Apply|Analyze>",
      "prerequisiteChain": ["<parent nodeIds>"],
      "stimulus": "<passage text or null if not needed>",
      "stimulusGroup": "<shared ID if multiple items use same passage, else null>",
      "stem": "<question text>",
      "options": [
        {{ "id": "A", "text": "<option text>", "isCorrect": false, "misconception": "<what error this catches>" }},
        {{ "id": "B", "text": "<option text>", "isCorrect": true, "misconception": null }},
        {{ "id": "C", "text": "<option text>", "isCorrect": false, "misconception": "<what error this catches>" }},
        {{ "id": "D", "text": "<option text>", "isCorrect": false, "misconception": "<what error this catches>" }}
      ],
      "correctAnswer": "B"
    }}
  ],
  "blueprint": {{
    "domains": [
      {{
        "name": "<unit/domain name>",
        "itemCount": <number>,
        "bloomsDistribution": {{
          "Remember": <count>,
          "Understand": <count>,
          "Apply": <count>,
          "Analyze": <count>
        }}
      }}
    ],
    "totalItems": <number>,
    "avgDifficulty": <number>,
    "difficultyDistribution": {{
      "easy": <count>,
      "moderateEasy": <count>,
      "medium": <count>,
      "moderateHard": <count>,
      "hard": <count>
    }}
  }},
  "cutScores": [
    {{
      "level": <integer 1-N>,
      "name": "<level name>",
      "description": "<what this level means>",
      "minCorrectPercent": <0-100>,
      "correspondingTreeDepth": <integer>,
      "gatewayNodesAtLevel": ["<nodeIds at this level>"]
    }}
  ]
}}

IMPORTANT:
- Return ONLY the JSON object. No markdown fences, no explanation text.
- Every item must have exactly 4 options (A, B, C, D).
- Exactly ONE option must have "isCorrect": true.
- The "correctAnswer" field must match the id of the correct option.
- Shuffle which option letter is correct (don't always make it the same letter).
- Cover ALL units/subgraphs in the tree — no domain should have zero items.
"""

    return system_msg, user_msg


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        course_id = body.get("courseId", "").strip()
        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        if not ANTHROPIC_API_KEY:
            send_json(self, {"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        # Check if there's already a job in progress
        existing_job = kv_get(f"diagnostic_job:{course_id}")
        if isinstance(existing_job, dict) and existing_job.get("status") == "processing":
            send_json(self, {
                "jobId": course_id,
                "batchId": existing_job.get("batchId", ""),
                "status": "processing",
                "message": "Diagnostic generation already in progress",
            })
            return

        # Load skill tree from KV
        saved_tree = kv_get(f"skill_tree:{course_id}")
        if not isinstance(saved_tree, dict) or not saved_tree.get("mermaid"):
            send_json(self, {
                "error": "No skill tree found for this course. Generate the skill tree first in Edit Course."
            }, 400)
            return

        mermaid_code = saved_tree["mermaid"]
        course_title = saved_tree.get("courseTitle", "Unknown Course")

        # Filter by selected units if specified
        selected_units = body.get("selectedUnits", [])
        if isinstance(selected_units, list) and len(selected_units) > 0:
            mermaid_code = _filter_mermaid_by_units(mermaid_code, selected_units)

        # Parse mermaid structure
        structure = _parse_mermaid_structure(mermaid_code)
        if structure["node_count"] < 5:
            send_json(self, {
                "error": f"Skill tree has only {structure['node_count']} nodes. Need at least 5 to generate a diagnostic."
            }, 400)
            return

        # Delete any existing diagnostic (for regeneration)
        kv_delete(f"diagnostic:{course_id}")

        # Build prompt
        system_msg, user_msg = _build_prompt(course_title, mermaid_code, structure)

        # Submit to Anthropic Batch API
        try:
            batch_payload = {
                "requests": [
                    {
                        "custom_id": f"diagnostic-{course_id}",
                        "params": {
                            "model": MODEL,
                            "max_tokens": 128000,
                            "thinking": {
                                "type": "enabled",
                                "budget_tokens": 50000,
                            },
                            "system": system_msg,
                            "messages": [
                                {"role": "user", "content": user_msg}
                            ],
                        },
                    }
                ]
            }

            resp = requests.post(
                ANTHROPIC_BATCH_URL,
                headers=_anthropic_headers(),
                json=batch_payload,
                timeout=30,
            )

            if resp.status_code not in (200, 201):
                error_detail = ""
                try:
                    error_detail = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    error_detail = resp.text[:200]
                send_json(self, {
                    "error": f"Anthropic API error ({resp.status_code}): {error_detail}",
                }, 500)
                return

            batch_data = resp.json()
            batch_id = batch_data.get("id", "")

            # Save job metadata to KV
            kv_set(f"diagnostic_job:{course_id}", {
                "batchId": batch_id,
                "status": "processing",
                "createdAt": time.time(),
                "courseTitle": course_title,
                "nodeCount": structure["node_count"],
                "model": MODEL,
            })

            send_json(self, {
                "jobId": course_id,
                "batchId": batch_id,
                "status": "processing",
                "nodeCount": structure["node_count"],
                "courseTitle": course_title,
            })

        except Exception as e:
            send_json(self, {"error": f"Failed to submit batch: {str(e)}"}, 500)
