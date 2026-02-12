"""POST /api/mark-content-complete — Mark article/video as complete.

Two-pronged approach (both tested and verified working):
1. OneRoster assessmentResult — writes to the resource's own ALI
2. Caliper ActivityCompletedEvent — the official Timeback completion signal

Body:
  studentId: string (required)
  resourceId: string (required) - plain resource sourcedId
  componentResId: string (required) - courseComponentResource sourcedId (USHI23-l46-r104170-v1)
  assessmentLineItemSourcedId: string (required) - the resource's own ALI
  contentType: string (optional) - "video" or "article"
  title: string (optional)
  email: string (required for Caliper) - student email
  courseId: string (optional) - course sourcedId
  courseName: string (optional)
"""

import json
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, get_token, send_json


CALIPER_URL = "https://caliper.alpha-1edtech.ai/caliper/event"
SENSOR_ID = "https://alphalearn.alpha.school"


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
        line_item_id = body.get("assessmentLineItemSourcedId", "")
        content_type = body.get("contentType", "content")
        title = body.get("title", resource_id)
        email = body.get("email", "")
        course_id = body.get("courseId", "")
        course_name = body.get("courseName", "")

        if not student_id or not line_item_id:
            send_json(self, {
                "error": "Missing studentId or assessmentLineItemSourcedId",
                "receivedALI": line_item_id,
                "receivedComponentResId": component_res_id,
            }, 400)
            return

        now = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        result_id = str(uuid.uuid4())
        results = {"oneroster": False, "caliper": False}

        # ── 1. OneRoster: write assessmentResult to the resource's own ALI ──
        try:
            headers = api_headers()
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
            results["oneroster"] = resp.status_code in (200, 201)
            if not results["oneroster"]:
                results["oneroster_status"] = resp.status_code
                results["oneroster_body"] = resp.text[:300]
        except Exception as e:
            results["oneroster_error"] = str(e)

        # ── 2. Caliper: ActivityCompletedEvent (official Timeback format) ──
        if email:
            try:
                token = get_token()
                caliper_event = {
                    "@context": "http://purl.imsglobal.org/ctx/caliper/v1p2",
                    "id": f"urn:uuid:{run_id}",
                    "type": "ActivityEvent",
                    "action": "Completed",
                    "profile": "TimebackProfile",
                    "eventTime": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "actor": {
                        "id": f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{student_id}",
                        "type": "TimebackUser",
                        "email": email,
                    },
                    "object": {
                        "id": f"{SENSOR_ID}/activities/{component_res_id}",
                        "type": "TimebackActivityContext",
                        "subject": "Social Studies",
                        "app": {"name": "AlphaLearn"},
                        "activity": {
                            "id": f"{SENSOR_ID}/activities/{component_res_id}",
                            "name": component_res_id,
                        },
                        "course": {
                            "code": course_id or component_res_id.split("-")[0],
                            "name": course_name or "",
                        },
                        "process": True,
                    },
                    "generated": {
                        "id": f"{API_BASE}/ims/metrics/collections/activity/{run_id}",
                        "type": "TimebackActivityMetricsCollection",
                        "items": [{"type": "xpEarned", "value": 0}],
                    },
                    "edApp": SENSOR_ID,
                    "extensions": {"runId": run_id, "courseId": course_id},
                }
                envelope = {
                    "sensor": SENSOR_ID,
                    "sendTime": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "dataVersion": "http://purl.imsglobal.org/ctx/caliper/v1p2",
                    "data": [caliper_event],
                }
                resp = requests.post(
                    CALIPER_URL,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=envelope,
                    timeout=15,
                )
                results["caliper"] = resp.status_code == 200
                if not results["caliper"]:
                    results["caliper_status"] = resp.status_code
                    results["caliper_body"] = resp.text[:300]
            except Exception as e:
                results["caliper_error"] = str(e)

        send_json(self, {
            "success": results["oneroster"] or results["caliper"],
            "resourceId": resource_id,
            "componentResId": component_res_id,
            "contentType": content_type,
            "results": results,
        })
