"""POST /api/generate-skill-tree — Submit a skill tree generation job.

Receives { courseId, courseTitle, courseCode }.
Fetches the lesson plan tree from PowerPath for context,
builds a Claude prompt, submits it to the Anthropic Batch API,
and saves job metadata to KV for polling.
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import API_BASE, api_headers, send_json
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


def _fetch_lesson_tree(course_id: str) -> list[dict]:
    """Fetch the PowerPath lesson plan tree for a course.
    Returns a list of unit dicts with nested lesson names."""
    try:
        headers = api_headers()
        resp = requests.get(
            f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}",
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _extract_lesson_names(tree_data) -> str:
    """Walk the tree structure and extract unit/lesson names as a formatted string."""
    lines = []

    def walk(node, depth=0):
        if isinstance(node, dict):
            name = (
                node.get("title")
                or node.get("name")
                or node.get("label")
                or ""
            )
            ntype = (node.get("type") or node.get("nodeType") or "").lower()
            if name:
                indent = "  " * depth
                prefix = "Unit" if "unit" in ntype or depth == 0 else "Lesson"
                lines.append(f"{indent}- {prefix}: {name}")

            # Recurse into children
            children = (
                node.get("children")
                or node.get("lessons")
                or node.get("items")
                or node.get("units")
                or []
            )
            if isinstance(children, list):
                for child in children:
                    walk(child, depth + 1)

        elif isinstance(node, list):
            for item in node:
                walk(item, depth)

    walk(tree_data)
    return "\n".join(lines) if lines else "No lesson data available."


def _build_prompt(course_title: str, course_code: str, lesson_names: str) -> tuple[str, str]:
    """Build the system and user messages for Claude."""

    system_msg = (
        "You are an expert AP curriculum designer with deep knowledge of "
        "peer-reviewed pedagogical research. You create detailed skill "
        "dependency trees that map the micro-skills students must master "
        "for AP courses."
    )

    user_msg = f"""Create a comprehensive skill tree for the following AP course based on peer-reviewed, pedagogically sound studies.

**Course**: {course_title} ({course_code})

**Units and Lessons**:
{lesson_names}

**Requirements**:
1. Build a mermaid flowchart mapping micro-skills with prerequisite relationships (you need to know X to know Y).
2. Be extremely detailed — aim for hundreds of specific skill nodes.
3. All skills must be FACT-BASED and CONTENT-SPECIFIC, not meta-cognitive.
   - GOOD: "Can identify that George Washington was the first US president"
   - GOOD: "Can identify logos as an appeal to logic in rhetoric"
   - GOOD: "Can solve quadratic equations using the quadratic formula"
   - BAD: "Can answer MCQ questions correctly"
   - BAD: "Understands the unit material"
   - BAD: "Able to identify an MCQ question"
4. Organize into subgraphs by unit/topic area.
5. Show clear prerequisite chains between skills.
6. Connect cross-unit dependencies where they exist.

**Output format**: Return ONLY a mermaid flowchart. No other text before or after the mermaid code.
Use this exact structure:

graph TD
    subgraph U1["Unit 1: Topic Name"]
        U1S1["Skill description"] --> U1S2["Dependent skill"]
        U1S2 --> U1S3["Further skill"]
    end
    subgraph U2["Unit 2: Another Topic"]
        U2S1["Skill description"] --> U2S2["Dependent skill"]
    end
    U1S3 --> U2S1

Rules for the mermaid code:
- Use unique node IDs like U1S1, U1S2, U2S1, etc.
- Wrap ALL node labels in square brackets with double quotes: U1S1["Label here"]
- Use --> for prerequisite arrows
- Use subgraph/end for each unit
- Do NOT use special characters in labels that would break mermaid syntax (no parentheses, no quotes within quotes, no semicolons in labels)
- Do NOT include ```mermaid or ``` markers — return the raw mermaid code only"""

    return system_msg, user_msg


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        # Parse body
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        course_id = body.get("courseId", "").strip()
        course_title = body.get("courseTitle", "").strip()
        course_code = body.get("courseCode", "").strip()

        if not course_id or not course_title:
            send_json(self, {"error": "Missing courseId or courseTitle"}, 400)
            return

        if not ANTHROPIC_API_KEY:
            send_json(self, {"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        # Check if there's already a job in progress
        existing_job = kv_get(f"skill_tree_job:{course_id}")
        if isinstance(existing_job, dict) and existing_job.get("status") == "processing":
            send_json(self, {
                "jobId": course_id,
                "batchId": existing_job.get("batchId", ""),
                "status": "processing",
                "message": "Generation already in progress",
            })
            return

        # Delete any existing skill tree (for regeneration)
        kv_delete(f"skill_tree:{course_id}")

        # Fetch lesson plan tree for context
        tree_data = _fetch_lesson_tree(course_id)
        lesson_names = _extract_lesson_names(tree_data)

        # Build prompt
        system_msg, user_msg = _build_prompt(course_title, course_code, lesson_names)

        # Submit to Anthropic Batch API
        try:
            batch_payload = {
                "requests": [
                    {
                        "custom_id": f"skill-tree-{course_id}",
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
            kv_set(f"skill_tree_job:{course_id}", {
                "batchId": batch_id,
                "status": "processing",
                "createdAt": time.time(),
                "courseTitle": course_title,
                "courseCode": course_code,
                "model": MODEL,
            })

            send_json(self, {
                "jobId": course_id,
                "batchId": batch_id,
                "status": "processing",
            })

        except Exception as e:
            send_json(self, {"error": f"Failed to submit batch: {str(e)}"}, 500)
