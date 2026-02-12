"""POST /api/submit-result — Record a result via OneRoster Gradebook.

Two-step process:
  1. PUT (upsert) an AssessmentLineItem so the reference exists
  2. PUT (upsert) an AssessmentResult referencing that line item
"""

import json
import hashlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


def _deterministic_id(seed: str) -> str:
    """Generate a stable UUID-like ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _uuid():
    import uuid
    return str(uuid.uuid4())


GRADEBOOK = f"{API_BASE}/ims/oneroster/gradebook/v1p2"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON body"}, 400)
            return

        student_id = body.get("studentSourcedId", "")
        line_item_id = body.get("assessmentLineItemSourcedId", "")
        score = body.get("score")
        score_status = body.get("scoreStatus", "fully graded")
        comment = body.get("comment", "")
        metadata = body.get("metadata") or {}
        lesson_title = metadata.get("timeback.lessonTitle", "") or body.get("lessonTitle", "")

        if not student_id:
            send_json(self, {"error": "Missing studentSourcedId"}, 400)
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        headers = api_headers()
        debug = []

        # ── Step 1: Ensure the AssessmentLineItem exists (upsert) ──
        # Use a deterministic ID from the original resource ID so repeated
        # attempts for the same quiz always reference the same line item.
        ali_seed = line_item_id or lesson_title or "unknown"
        ali_id = _deterministic_id(f"ali:{ali_seed}")
        ali_title = lesson_title or line_item_id or "Quiz"

        ali_payload = {
            "assessmentLineItem": {
                "sourcedId": ali_id,
                "status": "active",
                "title": ali_title,
                "description": f"Auto-created for {ali_title}",
                "assignDate": now,
                "dueDate": now,
                "resultValueMin": 0.0,
                "resultValueMax": 100.0,
            }
        }

        ali_url = f"{GRADEBOOK}/assessmentLineItems/{ali_id}"
        try:
            resp = requests.put(ali_url, headers=headers, json=ali_payload, timeout=15)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.put(ali_url, headers=headers, json=ali_payload, timeout=15)
            debug.append({
                "step": "1_upsert_lineItem",
                "url": ali_url,
                "status": resp.status_code,
                "body": resp.text[:300],
            })
        except Exception as e:
            debug.append({"step": "1_upsert_lineItem", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": "Failed to create assessmentLineItem",
                "debug": debug,
            }, 502)
            return

        if resp.status_code not in (200, 201):
            send_json(self, {
                "status": "error",
                "message": f"AssessmentLineItem upsert failed ({resp.status_code})",
                "debug": debug,
            }, 502)
            return

        # ── Step 2: Create the AssessmentResult ──
        result_id = _deterministic_id(f"result:{ali_seed}:{student_id}:{now[:10]}")

        result_payload = {
            "assessmentResult": {
                "sourcedId": result_id,
                "status": "active",
                "student": {"sourcedId": student_id},
                "assessmentLineItem": {"sourcedId": ali_id},
                "score": score,
                "scoreStatus": score_status,
                "scoreDate": now,
                "comment": comment or None,
                "metadata": metadata or None,
            }
        }

        result_url = f"{GRADEBOOK}/assessmentResults/{result_id}"
        try:
            resp = requests.put(result_url, headers=headers, json=result_payload, timeout=15)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.put(result_url, headers=headers, json=result_payload, timeout=15)
            debug.append({
                "step": "2_upsert_result",
                "url": result_url,
                "status": resp.status_code,
                "body": resp.text[:300],
            })
        except Exception as e:
            debug.append({"step": "2_upsert_result", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": "Failed to create assessmentResult",
                "debug": debug,
            }, 502)
            return

        if resp.status_code in (200, 201):
            try:
                data = resp.json()
            except Exception:
                data = {}
            send_json(self, {
                "status": "success",
                "assessmentLineItemId": ali_id,
                "resultId": result_id,
                "response": data,
                "debug": debug,
            }, 201)
        else:
            send_json(self, {
                "status": "error",
                "message": f"AssessmentResult upsert failed ({resp.status_code})",
                "debug": debug,
            }, 502)
