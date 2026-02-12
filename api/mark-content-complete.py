"""POST /api/mark-content-complete — Mark article/video as complete.

For non-quiz content (articles, videos), this:
1. Records a OneRoster result with score 100, status 'fully graded'
2. Creates a Caliper completion event

Body:
  studentId: string (required) - student sourcedId
  resourceId: string (required) - resource/lesson sourcedId
  contentType: string (optional) - "video" or "article"
  title: string (optional) - content title for logging
  email: string (optional) - student email for Caliper
  courseId: string (optional) - course sourcedId
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
        content_type = body.get("contentType", "content")
        title = body.get("title", resource_id)
        email = body.get("email", "")
        course_id = body.get("courseId", "")

        if not student_id or not resource_id:
            send_json(self, {"error": "Missing studentId or resourceId"}, 400)
            return

        headers = api_headers()
        results = {"oneroster": False, "caliper": False}

        # 1. Create OneRoster result (this is what the course page reads)
        try:
            result_payload = {
                "result": {
                    "student": {"sourcedId": student_id},
                    "lineItem": {"sourcedId": resource_id},
                    "score": 100,
                    "scoreStatus": "fully graded",
                    "comment": f"{title} - {content_type} completed",
                    "metadata": {
                        "timeback.xp": 0,
                        "timeback.passed": True,
                        "timeback.contentType": content_type,
                        "timeback.completedAt": datetime.now(timezone.utc).isoformat()
                    }
                }
            }
            
            resp = requests.post(
                f"{API_BASE}/ims/oneroster/gradebook/v1p2/results",
                headers=headers,
                json=result_payload,
                timeout=15
            )
            
            if resp.status_code in (200, 201):
                results["oneroster"] = True
            else:
                results["oneroster_post_status"] = resp.status_code
                results["oneroster_post_body"] = resp.text[:300]
                # Try alternative endpoint
                resp2 = requests.put(
                    f"{API_BASE}/ims/oneroster/gradebook/v1p2/results/{resource_id}-{student_id}",
                    headers=headers,
                    json=result_payload,
                    timeout=15
                )
                results["oneroster"] = resp2.status_code in (200, 201)
                if not results["oneroster"]:
                    results["oneroster_put_status"] = resp2.status_code
                    results["oneroster_put_body"] = resp2.text[:300]
        except Exception as e:
            results["oneroster_error"] = str(e)

        # 2. Send Caliper completion event
        if email:
            try:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                run_id = str(uuid.uuid4())
                
                caliper_event = {
                    "@context": "http://purl.imsglobal.org/ctx/caliper/v1p2",
                    "id": f"urn:uuid:{run_id}",
                    "type": "ViewEvent" if content_type == "video" else "NavigationEvent",
                    "action": "Completed",
                    "eventTime": now,
                    "actor": {
                        "id": f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{student_id}",
                        "type": "Person",
                        "email": email
                    },
                    "object": {
                        "id": f"{SENSOR_ID}/resources/{resource_id}",
                        "type": "VideoObject" if content_type == "video" else "Document",
                        "name": title
                    },
                    "edApp": SENSOR_ID,
                    "extensions": {
                        "resourceId": resource_id,
                        "contentType": content_type,
                        "courseId": course_id
                    }
                }
                
                envelope = {
                    "sensor": SENSOR_ID,
                    "sendTime": now,
                    "dataVersion": "http://purl.imsglobal.org/ctx/caliper/v1p2",
                    "data": [caliper_event]
                }
                
                token = get_token()
                resp = requests.post(
                    CALIPER_URL,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=envelope,
                    timeout=15
                )
                results["caliper"] = resp.status_code in (200, 201, 204)
            except Exception as e:
                results["caliper_error"] = str(e)

        send_json(self, {
            "success": results["oneroster"] or results["caliper"],
            "resourceId": resource_id,
            "contentType": content_type,
            "results": results
        })
