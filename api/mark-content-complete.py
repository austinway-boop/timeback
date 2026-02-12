"""POST /api/mark-content-complete — Mark article/video as complete.

Writes a OneRoster assessmentResult to the resource's own
assessmentLineItemSourcedId (each video/article has its own ALI).

Body:
  studentId: string (required) - student sourcedId
  resourceId: string (required) - resource sourcedId
  assessmentLineItemSourcedId: string (required) - the resource's own ALI
  contentType: string (optional) - "video" or "article"
  title: string (optional) - content title for logging
"""

import json
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON body"}, 400)
            return

        student_id = body.get("studentId", "")
        resource_id = body.get("resourceId", "")
        line_item_id = body.get("assessmentLineItemSourcedId", "")
        content_type = body.get("contentType", "content")
        title = body.get("title", resource_id)

        if not student_id or not line_item_id:
            send_json(self, {"error": "Missing studentId or assessmentLineItemSourcedId"}, 400)
            return

        headers = api_headers()
        now = datetime.now(timezone.utc)
        result_id = str(uuid.uuid4())

        try:
            result_payload = {
                "assessmentResult": {
                    "sourcedId": result_id,
                    "status": "active",
                    "dateLastModified": now.isoformat(),
                    "assessmentLineItem": {"sourcedId": line_item_id},
                    "student": {"sourcedId": student_id},
                    "score": 0,
                    "scoreDate": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "scoreStatus": "fully graded",
                    "comment": f"{title} - {content_type} completed",
                    "inProgress": "false",
                    "incomplete": "false",
                    "late": "false",
                    "missing": "false",
                    "metadata": {
                        "timeback.xp": 0,
                        "timeback.passed": True,
                        "timeback.contentType": content_type,
                    },
                }
            }

            resp = requests.put(
                f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentResults/{result_id}",
                headers=headers,
                json=result_payload,
                timeout=15,
            )

            success = resp.status_code in (200, 201)
            send_json(self, {
                "success": success,
                "resourceId": resource_id,
                "contentType": content_type,
                "resultId": result_id,
                "status": resp.status_code,
                "error": resp.text[:300] if not success else None,
            })
        except Exception as e:
            send_json(self, {"success": False, "error": str(e)}, 500)
