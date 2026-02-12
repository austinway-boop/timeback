"""POST /api/mark-content-complete — Mark article/video as complete.

Calls the Timeback platform's completeVideo server function (same as the
working alpha.timeback.com app), then falls back to a direct OneRoster
assessmentResult write.

Body:
  studentId: string (required) - student sourcedId
  resourceId: string (required) - resource sourcedId
  componentResId: string (preferred) - courseComponentResource sourcedId (e.g. USHI23-l45-r104167-v1)
  contentType: string (optional) - "video" or "article"
  title: string (optional) - content title for logging
  assessmentLineItemSourcedId: string (optional) - for OneRoster fallback
"""

import json
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


TIMEBACK_BASE = "https://alpha.timeback.com/_serverFn"
COMPLETE_VIDEO_FN = (
    "src_features_recommendations_actions_completeVideo_ts"
    "--completeVideo_createServerFn_handler"
)


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
        component_res_id = body.get("componentResId", "") or resource_id
        content_type = body.get("contentType", "content")
        title = body.get("title", resource_id)
        line_item_id = body.get("assessmentLineItemSourcedId", "") or resource_id

        if not student_id or not resource_id:
            send_json(self, {"error": "Missing studentId or resourceId"}, 400)
            return

        results = {"timeback": False, "oneroster": False}

        # ── 1. Primary: call Timeback completeVideo (same as working app) ──
        try:
            resp = requests.post(
                f"{TIMEBACK_BASE}/{COMPLETE_VIDEO_FN}?createServerFn",
                json={
                    "data": {
                        "userId": student_id,
                        "videoId": component_res_id,
                    },
                    "context": {},
                },
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                tb_data = resp.json()
                results["timeback"] = (
                    tb_data.get("result", {}).get("success", False) is True
                )
            else:
                results["timeback_status"] = resp.status_code
                results["timeback_body"] = resp.text[:300]
        except Exception as e:
            results["timeback_error"] = str(e)

        # ── 2. Fallback: OneRoster assessmentResult ──
        if not results["timeback"]:
            try:
                headers = api_headers()
                now = datetime.now(timezone.utc)
                result_id = str(uuid.uuid4())
                result_payload = {
                    "assessmentResult": {
                        "sourcedId": result_id,
                        "status": "active",
                        "dateLastModified": now.isoformat(),
                        "assessmentLineItem": {"sourcedId": line_item_id},
                        "student": {"sourcedId": student_id},
                        "score": 100,
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
                if resp.status_code in (200, 201):
                    results["oneroster"] = True
                else:
                    results["oneroster_status"] = resp.status_code
                    results["oneroster_body"] = resp.text[:300]
            except Exception as e:
                results["oneroster_error"] = str(e)

        send_json(self, {
            "success": results["timeback"] or results["oneroster"],
            "resourceId": resource_id,
            "componentResId": component_res_id,
            "contentType": content_type,
            "results": results,
        })
