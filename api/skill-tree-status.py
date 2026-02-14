"""GET /api/skill-tree-status?courseId=... — Check skill tree generation status.

If a completed tree exists in KV, return it immediately.
If a job is in progress, poll the Anthropic Batch API for status.
When the batch is done, extract the mermaid code, save to KV, and return it.
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


def _extract_mermaid(text: str) -> str:
    """Extract mermaid code from Claude's response.
    Handles both raw mermaid and code-fenced mermaid."""
    # Try to extract from ```mermaid ... ``` blocks
    match = re.search(r'```mermaid\s*\n(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try to extract from ``` ... ``` blocks
    match = re.search(r'```\s*\n(.*?)```', text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        if code.startswith('graph') or code.startswith('flowchart'):
            return code

    # If no fences, check if the whole response looks like mermaid
    stripped = text.strip()
    if stripped.startswith('graph') or stripped.startswith('flowchart'):
        return stripped

    return text.strip()


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
                    error_info = result_body.get("error", {})
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

        # 1. Check if a completed skill tree exists in KV
        saved_tree = kv_get(f"skill_tree:{course_id}")
        if isinstance(saved_tree, dict) and saved_tree.get("mermaid"):
            send_json(self, {
                "status": "done",
                "mermaid": saved_tree["mermaid"],
                "generatedAt": saved_tree.get("generatedAt", ""),
                "courseTitle": saved_tree.get("courseTitle", ""),
                "model": saved_tree.get("model", ""),
            })
            return

        # 2. Check if there's a job in progress
        job = kv_get(f"skill_tree_job:{course_id}")
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
                    mermaid_code = _extract_mermaid(text_content)

                    # Save completed tree to KV
                    tree_data = {
                        "mermaid": mermaid_code,
                        "generatedAt": time.time(),
                        "courseTitle": job.get("courseTitle", ""),
                        "courseCode": job.get("courseCode", ""),
                        "model": job.get("model", ""),
                    }
                    kv_set(f"skill_tree:{course_id}", tree_data)

                    # Clean up job
                    kv_delete(f"skill_tree_job:{course_id}")

                    send_json(self, {
                        "status": "done",
                        "mermaid": mermaid_code,
                        "generatedAt": tree_data["generatedAt"],
                        "courseTitle": tree_data["courseTitle"],
                        "model": tree_data["model"],
                    })
                    return
                else:
                    # Results fetch failed
                    kv_delete(f"skill_tree_job:{course_id}")
                    send_json(self, {
                        "status": "error",
                        "error": "Failed to retrieve results from completed batch.",
                    })
                    return
            else:
                # Batch ended but no successes
                errored = request_counts.get("errored", 0)
                expired = request_counts.get("expired", 0)
                canceled = request_counts.get("canceled", 0)
                kv_delete(f"skill_tree_job:{course_id}")
                send_json(self, {
                    "status": "error",
                    "error": f"Batch completed with no successful results. Errored: {errored}, Expired: {expired}, Canceled: {canceled}",
                })
                return

        elif processing_status == "canceling":
            send_json(self, {
                "status": "error",
                "error": "Batch was canceled.",
            })
            kv_delete(f"skill_tree_job:{course_id}")
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
                "message": "Claude is working on your skill tree...",
            })
