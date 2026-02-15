"""GET /api/relevance-status?courseId=... — Check relevance analysis status.

If completed results exist in KV, return them.
If a job is in progress, poll the Anthropic Batch API.
When done, fetch results, merge all chunks, save to KV.
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
    """Extract JSON from Claude's response."""
    match = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    depth = 0
    start = -1
    for i, ch in enumerate(stripped):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(stripped[start:i + 1])
                except json.JSONDecodeError:
                    start = -1
    return None


def _fetch_batch_status(batch_id: str) -> dict | None:
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


def _fetch_batch_results(batch_id: str) -> list[dict]:
    """Fetch all results from a completed batch."""
    results = []
    try:
        resp = requests.get(
            f"{ANTHROPIC_BATCH_URL}/{batch_id}/results",
            headers=_anthropic_headers(),
            timeout=60,
        )
        if resp.status_code != 200:
            return []
        text = resp.text.strip()
        for line in text.split("\n"):
            if not line.strip():
                continue
            try:
                result = json.loads(line)
                result_body = result.get("result", {})
                custom_id = result.get("custom_id", "")
                if result_body.get("type") == "succeeded":
                    message = result_body.get("message", {})
                    content_blocks = message.get("content", [])
                    for block in content_blocks:
                        if block.get("type") == "text":
                            parsed = _extract_json(block.get("text", ""))
                            if parsed:
                                results.append({
                                    "custom_id": custom_id,
                                    "data": parsed,
                                })
                            break
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return results


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

        # 1. Check for completed results
        saved = kv_get(f"relevance_analysis:{course_id}")
        if isinstance(saved, dict) and saved.get("results"):
            send_json(self, {
                "status": "done",
                "results": saved["results"],
                "questionCount": saved.get("questionCount", 0),
                "badCount": saved.get("badCount", 0),
                "generatedAt": saved.get("generatedAt", ""),
                "model": saved.get("model", ""),
            })
            return

        # 2. Check for in-progress job
        job = kv_get(f"relevance_job:{course_id}")
        if not isinstance(job, dict) or not job.get("batchId"):
            send_json(self, {"status": "none"})
            return

        batch_id = job["batchId"]
        created_at = job.get("createdAt", 0)
        chunk_count = job.get("chunkCount", 1)

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
                chunk_results = _fetch_batch_results(batch_id)
                if chunk_results:
                    merged = {}
                    for chunk in chunk_results:
                        if isinstance(chunk.get("data"), dict):
                            merged.update(chunk["data"])

                    # Count bad questions
                    bad_count = sum(
                        1 for v in merged.values()
                        if isinstance(v, dict) and not v.get("relevant", True)
                    )

                    analysis_data = {
                        "results": merged,
                        "questionCount": len(merged),
                        "badCount": bad_count,
                        "generatedAt": time.time(),
                        "model": job.get("model", ""),
                        "chunkCount": chunk_count,
                    }
                    kv_set(f"relevance_analysis:{course_id}", analysis_data)
                    kv_delete(f"relevance_job:{course_id}")

                    send_json(self, {
                        "status": "done",
                        "results": merged,
                        "questionCount": len(merged),
                        "badCount": bad_count,
                        "generatedAt": analysis_data["generatedAt"],
                        "model": analysis_data["model"],
                    })
                    return
                else:
                    kv_delete(f"relevance_job:{course_id}")
                    send_json(self, {
                        "status": "error",
                        "error": "Failed to retrieve or parse results from completed batch.",
                    })
                    return
            else:
                errored = request_counts.get("errored", 0)
                expired = request_counts.get("expired", 0)
                kv_delete(f"relevance_job:{course_id}")
                send_json(self, {
                    "status": "error",
                    "error": f"Batch completed with no successes. Errored: {errored}, Expired: {expired}",
                })
                return

        elif processing_status == "canceling":
            kv_delete(f"relevance_job:{course_id}")
            send_json(self, {"status": "error", "error": "Batch was canceled."})
            return

        else:
            elapsed = int(time.time() - created_at) if created_at else 0
            counts = batch_status.get("request_counts", {})
            send_json(self, {
                "status": "processing",
                "elapsed": elapsed,
                "succeeded": counts.get("succeeded", 0),
                "processing": counts.get("processing", 0),
                "chunkCount": chunk_count,
            })
