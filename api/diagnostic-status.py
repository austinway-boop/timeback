"""GET /api/diagnostic-status?courseId=... — Check diagnostic generation status.

If a completed diagnostic exists in KV, return it immediately.
If a job is in progress, poll the Anthropic Batch API for status.
When the batch is done, extract the JSON, validate it, save to KV, and return it.
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


def _extract_json(text: str) -> dict | None:
    """Extract JSON from Claude's response, handling potential markdown fences."""
    # Try to extract from ```json ... ``` blocks
    match = re.search(r'```json\s*\n(.*?)```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try to extract from ``` ... ``` blocks
    match = re.search(r'```\s*\n(.*?)```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try parsing the whole response as JSON
    stripped = text.strip()
    # Remove any leading/trailing non-JSON content
    # Find the first { and last }
    first_brace = stripped.find('{')
    last_brace = stripped.rfind('}')
    if first_brace >= 0 and last_brace > first_brace:
        try:
            return json.loads(stripped[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    return None


def _validate_diagnostic(data: dict) -> tuple[bool, str]:
    """Validate the structure of the generated diagnostic JSON."""
    if not isinstance(data, dict):
        return False, "Response is not a JSON object"

    items = data.get("items")
    if not isinstance(items, list) or len(items) < 5:
        return False, f"Expected at least 5 items, got {len(items) if isinstance(items, list) else 0}"

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"Item {i} is not an object"
        if not item.get("stem"):
            return False, f"Item {i} missing stem"
        options = item.get("options", [])
        if not isinstance(options, list) or len(options) < 2:
            return False, f"Item {i} has {len(options) if isinstance(options, list) else 0} options (need at least 2)"
        correct_count = sum(1 for o in options if o.get("isCorrect"))
        if correct_count != 1:
            # Try to fix: use correctAnswer field
            correct_letter = item.get("correctAnswer", "")
            if correct_letter:
                for o in options:
                    o["isCorrect"] = (o.get("id") == correct_letter)
                correct_count = sum(1 for o in options if o.get("isCorrect"))
            if correct_count != 1:
                return False, f"Item {i} has {correct_count} correct answers (need exactly 1)"

    return True, "OK"


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
        results_url = f"{ANTHROPIC_BATCH_URL}/{batch_id}/results"
        resp = requests.get(
            results_url,
            headers=_anthropic_headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return None

        # Results are JSONL — one line per request
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

                # Extract text content (skip thinking blocks)
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

        # 1. Check if a completed diagnostic exists in KV
        saved = kv_get(f"diagnostic:{course_id}")
        if isinstance(saved, dict) and saved.get("items"):
            send_json(self, {
                "status": "done",
                "diagnostic": saved,
                "generatedAt": saved.get("generatedAt", ""),
                "courseTitle": saved.get("courseTitle", ""),
                "itemCount": len(saved.get("items", [])),
            })
            return

        # 2. Check if there's a job in progress
        job = kv_get(f"diagnostic_job:{course_id}")
        if not isinstance(job, dict) or not job.get("batchId"):
            send_json(self, {"status": "none"})
            return

        batch_id = job["batchId"]
        created_at = job.get("createdAt", 0)

        # 3. Poll the Anthropic Batch API
        batch_status = _fetch_batch_status(batch_id)
        if not batch_status:
            send_json(self, {
                "status": "processing",
                "elapsed": int(time.time() - created_at) if created_at else 0,
                "message": "Checking batch status...",
            })
            return

        processing_status = batch_status.get("processing_status", "")

        if processing_status == "ended":
            # Batch is done — fetch results
            request_counts = batch_status.get("request_counts", {})

            if request_counts.get("succeeded", 0) > 0:
                text_content = _fetch_batch_results(batch_id)
                if text_content:
                    diagnostic_data = _extract_json(text_content)
                    if diagnostic_data:
                        # Validate
                        valid, msg = _validate_diagnostic(diagnostic_data)
                        if valid:
                            # Add metadata
                            diagnostic_data["generatedAt"] = time.time()
                            diagnostic_data["courseTitle"] = job.get("courseTitle", "")
                            diagnostic_data["courseId"] = course_id
                            diagnostic_data["model"] = job.get("model", "")

                            # Save completed diagnostic to KV
                            kv_set(f"diagnostic:{course_id}", diagnostic_data)
                            kv_delete(f"diagnostic_job:{course_id}")

                            send_json(self, {
                                "status": "done",
                                "diagnostic": diagnostic_data,
                                "generatedAt": diagnostic_data["generatedAt"],
                                "courseTitle": diagnostic_data["courseTitle"],
                                "itemCount": len(diagnostic_data.get("items", [])),
                            })
                            return
                        else:
                            # Validation failed — save raw but flag it
                            diagnostic_data["generatedAt"] = time.time()
                            diagnostic_data["courseTitle"] = job.get("courseTitle", "")
                            diagnostic_data["courseId"] = course_id
                            diagnostic_data["model"] = job.get("model", "")
                            diagnostic_data["_validationWarning"] = msg

                            kv_set(f"diagnostic:{course_id}", diagnostic_data)
                            kv_delete(f"diagnostic_job:{course_id}")

                            send_json(self, {
                                "status": "done",
                                "diagnostic": diagnostic_data,
                                "warning": f"Validation issue: {msg}",
                                "generatedAt": diagnostic_data["generatedAt"],
                                "courseTitle": diagnostic_data["courseTitle"],
                                "itemCount": len(diagnostic_data.get("items", [])),
                            })
                            return
                    else:
                        kv_delete(f"diagnostic_job:{course_id}")
                        send_json(self, {
                            "status": "error",
                            "error": "Failed to parse JSON from AI response.",
                        })
                        return
                else:
                    kv_delete(f"diagnostic_job:{course_id}")
                    send_json(self, {
                        "status": "error",
                        "error": "Failed to retrieve results from completed batch.",
                    })
                    return
            else:
                errored = request_counts.get("errored", 0)
                expired = request_counts.get("expired", 0)
                canceled = request_counts.get("canceled", 0)
                kv_delete(f"diagnostic_job:{course_id}")
                send_json(self, {
                    "status": "error",
                    "error": f"Batch completed with no successes. Errored: {errored}, Expired: {expired}, Canceled: {canceled}",
                })
                return

        elif processing_status == "canceling":
            send_json(self, {
                "status": "error",
                "error": "Batch was canceled.",
            })
            kv_delete(f"diagnostic_job:{course_id}")
            return

        else:
            # Still in progress
            elapsed = int(time.time() - created_at) if created_at else 0
            counts = batch_status.get("request_counts", {})
            send_json(self, {
                "status": "processing",
                "elapsed": elapsed,
                "processing": counts.get("processing", 0),
                "succeeded": counts.get("succeeded", 0),
                "message": "AI is generating your diagnostic assessment...",
            })
