"""GET /api/lesson-mapping-status?courseId=... — Check lesson mapping status.

If a completed mapping exists in KV, return it immediately.
If a job is in progress, poll the Anthropic Batch API for status.
When done, extract JSON mapping from Claude response, save to KV, return.
"""

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import send_json, get_query_params
from api._kv import kv_get, kv_set, kv_delete

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BATCH_URL = "https://api.anthropic.com/v1/messages/batches"
ANTHROPIC_VERSION = "2023-06-01"


def _anthropic_headers():
    return {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _extract_json_mapping(text: str) -> dict | None:
    """Extract JSON mapping from Claude's response."""
    # Try to find JSON in code blocks
    match = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try to parse the whole response as JSON
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try to find the largest JSON object in the text
    # Look for { ... } blocks
    brace_depth = 0
    start = -1
    for i, ch in enumerate(stripped):
        if ch == '{':
            if brace_depth == 0:
                start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and start >= 0:
                try:
                    candidate = stripped[start:i + 1]
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1

    return None


def _fetch_batch_status(batch_id: str) -> dict | None:
    """Check the status of an Anthropic message batch."""
    try:
        resp = requests.get(
            f"{ANTHROPIC_BATCH_URL}/{batch_id}",
            headers=_anthropic_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _fetch_batch_results(batch_id: str) -> str | None:
    """Fetch results from a completed batch. Returns the text content."""
    try:
        resp = requests.get(
            f"{ANTHROPIC_BATCH_URL}/{batch_id}/results",
            headers=_anthropic_headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return None

        text = resp.text.strip()
        for line in text.split("\n"):
            if not line.strip():
                continue
            try:
                result = json.loads(line)
                result_body = result.get("result", {})
                if result_body.get("type") != "succeeded":
                    return None
                message = result_body.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        return block.get("text", "")
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return None


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "") or params.get("jobId", "")

        if not course_id:
            send_json(self, {"error": "Missing courseId parameter"}, 400)
            return

        # 1. Check for completed mapping
        saved = kv_get(f"lesson_mapping:{course_id}")
        if isinstance(saved, dict) and saved.get("mapping"):
            send_json(self, {
                "status": "done",
                "mapping": saved["mapping"],
                "generatedAt": saved.get("generatedAt", ""),
                "model": saved.get("model", ""),
            })
            return

        # 2. Check for in-progress job
        job = kv_get(f"lesson_mapping_job:{course_id}")
        if not isinstance(job, dict) or not job.get("batchId"):
            send_json(self, {"status": "none"})
            return

        batch_id = job["batchId"]
        created_at = job.get("createdAt", 0)

        # 3. Poll Anthropic
        batch_status = _fetch_batch_status(batch_id)
        if not batch_status:
            send_json(self, {
                "status": "processing",
                "elapsed": int(time.time() - created_at) if created_at else 0,
            })
            return

        processing_status = batch_status.get("processing_status", "")

        if processing_status == "ended":
            request_counts = batch_status.get("request_counts", {})

            if request_counts.get("succeeded", 0) > 0:
                text_content = _fetch_batch_results(batch_id)
                if text_content:
                    mapping = _extract_json_mapping(text_content)
                    if mapping and isinstance(mapping, dict):
                        mapping_data = {
                            "mapping": mapping,
                            "generatedAt": time.time(),
                            "model": job.get("model", ""),
                        }
                        kv_set(f"lesson_mapping:{course_id}", mapping_data)
                        kv_delete(f"lesson_mapping_job:{course_id}")
                        send_json(self, {
                            "status": "done",
                            "mapping": mapping,
                            "generatedAt": mapping_data["generatedAt"],
                            "model": mapping_data["model"],
                        })
                        return
                    else:
                        kv_delete(f"lesson_mapping_job:{course_id}")
                        send_json(self, {
                            "status": "error",
                            "error": "Failed to parse JSON mapping from Claude's response.",
                        })
                        return
                else:
                    kv_delete(f"lesson_mapping_job:{course_id}")
                    send_json(self, {
                        "status": "error",
                        "error": "Failed to retrieve results from completed batch.",
                    })
                    return
            else:
                errored = request_counts.get("errored", 0)
                expired = request_counts.get("expired", 0)
                kv_delete(f"lesson_mapping_job:{course_id}")
                send_json(self, {
                    "status": "error",
                    "error": f"Batch completed with no successes. Errored: {errored}, Expired: {expired}",
                })
                return

        elif processing_status == "canceling":
            kv_delete(f"lesson_mapping_job:{course_id}")
            send_json(self, {"status": "error", "error": "Batch was canceled."})
            return

        else:
            elapsed = int(time.time() - created_at) if created_at else 0
            send_json(self, {
                "status": "processing",
                "elapsed": elapsed,
                "message": "Claude is mapping lessons to skills...",
            })
