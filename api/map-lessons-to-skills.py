"""POST /api/map-lessons-to-skills — Map each lesson to skill nodes from the skill tree.

Receives { courseId }.
Loads the saved skill tree from KV, parses node IDs and labels,
fetches the lesson plan tree from PowerPath, builds a Claude prompt
to map each lesson to relevant skill IDs, submits via Anthropic Batch API.
"""

import json
import os
import re
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


def _parse_skill_nodes(mermaid_code: str) -> list[tuple[str, str]]:
    """Extract (nodeId, label) pairs from mermaid code."""
    nodes = {}
    for match in re.finditer(r'(\w+)\["([^"]+)"\]', mermaid_code):
        nid, label = match.group(1), match.group(2)
        if nid not in nodes:
            nodes[nid] = label
    return list(nodes.items())


def _fetch_lesson_tree(course_id: str) -> list:
    """Fetch the PowerPath lesson plan tree for a course."""
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


def _extract_lesson_names_flat(tree_data) -> list[str]:
    """Walk the tree and return a flat list of lesson names."""
    names = []

    def walk(node, depth=0):
        if isinstance(node, dict):
            name = (
                node.get("title")
                or node.get("name")
                or node.get("label")
                or ""
            )
            ntype = (node.get("type") or node.get("nodeType") or "").lower()
            # Only include actual lessons (not top-level units)
            if name and depth > 0:
                names.append(name)

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
    return names


def _build_prompt(skill_nodes: list[tuple[str, str]], lesson_names: list[str]) -> tuple[str, str]:
    """Build the system and user messages for Claude."""

    system_msg = (
        "You are an expert curriculum analyst specializing in AP courses. "
        "Your task is to map individual lessons to the specific skills they teach."
    )

    # Build compact skill list
    skill_list = "\n".join(f"  {nid}: {label}" for nid, label in skill_nodes)

    # Build lesson list
    lesson_list = "\n".join(f"  - {name}" for name in lesson_names)

    user_msg = f"""Below is a list of all skills in an AP course skill tree, and a list of all lessons in that course.

For each lesson, determine which skills from the skill tree are taught or covered in that lesson. A lesson may cover multiple skills, and a skill may appear in multiple lessons.

**ALL SKILL NODES:**
{skill_list}

**ALL LESSONS:**
{lesson_list}

**Instructions:**
1. For each lesson, identify the skill node IDs that are taught or covered in that lesson.
2. Be thorough — include all skills that a student would learn or practice in each lesson.
3. Use the exact skill node IDs from the list above.
4. Return ONLY a valid JSON object with no additional text.

**Output format** (return ONLY this JSON, nothing else):
{{
  "Lesson Name Here": ["U1S1", "U1S2", "U1S3"],
  "Another Lesson": ["U2S1", "U2S4"],
  ...
}}"""

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

        # Check for existing job
        existing_job = kv_get(f"lesson_mapping_job:{course_id}")
        if isinstance(existing_job, dict) and existing_job.get("status") == "processing":
            send_json(self, {
                "jobId": course_id,
                "batchId": existing_job.get("batchId", ""),
                "status": "processing",
                "message": "Lesson mapping already in progress",
            })
            return

        # Load saved skill tree
        saved_tree = kv_get(f"skill_tree:{course_id}")
        if not isinstance(saved_tree, dict) or not saved_tree.get("mermaid"):
            send_json(self, {"error": "No skill tree found. Generate the skill tree first."}, 400)
            return

        mermaid_code = saved_tree["mermaid"]
        skill_nodes = _parse_skill_nodes(mermaid_code)
        if not skill_nodes:
            send_json(self, {"error": "Could not parse any skill nodes from the skill tree."}, 400)
            return

        # Fetch lesson plan tree
        tree_data = _fetch_lesson_tree(course_id)
        lesson_names = _extract_lesson_names_flat(tree_data)
        if not lesson_names:
            send_json(self, {"error": "Could not fetch lesson names from PowerPath."}, 400)
            return

        # Delete existing mapping (for regeneration)
        kv_delete(f"lesson_mapping:{course_id}")

        # Build prompt
        system_msg, user_msg = _build_prompt(skill_nodes, lesson_names)

        # Submit to Anthropic Batch API
        try:
            batch_payload = {
                "requests": [
                    {
                        "custom_id": f"lesson-mapping-{course_id}",
                        "params": {
                            "model": MODEL,
                            "max_tokens": 64000,
                            "thinking": {
                                "type": "enabled",
                                "budget_tokens": 20000,
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
                send_json(self, {"error": f"Anthropic API error ({resp.status_code}): {error_detail}"}, 500)
                return

            batch_data = resp.json()
            batch_id = batch_data.get("id", "")

            kv_set(f"lesson_mapping_job:{course_id}", {
                "batchId": batch_id,
                "status": "processing",
                "createdAt": time.time(),
                "model": MODEL,
            })

            send_json(self, {
                "jobId": course_id,
                "batchId": batch_id,
                "status": "processing",
            })

        except Exception as e:
            send_json(self, {"error": f"Failed to submit batch: {str(e)}"}, 500)
