"""POST /api/activity-record — Record activity completion via SDK-style pipeline.

This mimics what @timeback/sdk's timeback.activity.record() does:
1. Sends ActivityCompletedEvent to Caliper
2. Triggers the full pipeline including gradebook and XP

Body:
  userId: string (required) - student sourcedId
  email: string (required) - student email for user resolution
  activityId: string (required) - unique activity identifier (e.g., lesson sourcedId)
  activityName: string (required) - human-readable name
  courseCode: string (required) - course sourcedId
  xpEarned: number (required)
  totalQuestions: number (optional)
  correctQuestions: number (optional)
  pctComplete: number (optional, 0-100)
  runId: string (optional) - UUID for correlating events

Docs: https://docs.timeback.com/beta/build-on-timeback/sdk/activity-tracking/reference#timebackactivityrecordparams
"""

import json
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from api._helpers import API_BASE, get_token, send_json

import requests

# The SDK uses this endpoint - let's try it
ACTIVITY_RECORD_URL = f"{API_BASE}/activity/record"
CALIPER_URL = "https://caliper.alpha-1edtech.ai/caliper/event"
SENSOR_ID = "https://alphalearn.alpha.school"


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

        user_id = body.get("userId", "")
        email = body.get("email", "")
        activity_id = body.get("activityId", "")
        activity_name = body.get("activityName", "")
        course_code = body.get("courseCode", "")
        xp_earned = body.get("xpEarned", 0)
        total_questions = body.get("totalQuestions")
        correct_questions = body.get("correctQuestions")
        pct_complete = body.get("pctComplete", 100)
        run_id = body.get("runId") or str(uuid.uuid4())

        if not user_id or not email or not activity_id or not activity_name or not course_code:
            send_json(self, {"error": "Missing required fields"}, 400)
            return

        token = get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        debug = []

        # Try 1: Direct SDK-style activity record endpoint
        sdk_payload = {
            "user": {
                "email": email,
                "timebackId": user_id
            },
            "activity": {
                "id": activity_id,
                "name": activity_name,
                "course": {"code": course_code}
            },
            "metrics": {
                "xpEarned": xp_earned,
                "pctComplete": pct_complete
            },
            "runId": run_id
        }
        if total_questions is not None:
            sdk_payload["metrics"]["totalQuestions"] = total_questions
        if correct_questions is not None:
            sdk_payload["metrics"]["correctQuestions"] = correct_questions

        try:
            resp = requests.post(ACTIVITY_RECORD_URL, headers=headers, json=sdk_payload, timeout=30)
            debug.append({
                "step": "1_sdk_activity_record",
                "url": ACTIVITY_RECORD_URL,
                "status": resp.status_code,
                "body": resp.text[:500]
            })
            
            if resp.status_code in (200, 201):
                send_json(self, {
                    "status": "success",
                    "method": "sdk_activity_record",
                    "response": resp.json() if resp.text else {},
                    "debug": debug
                })
                return
        except Exception as e:
            debug.append({"step": "1_sdk_activity_record", "error": str(e)})

        # Try 2: Caliper ActivityCompletedEvent with SDK-style format
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        metrics = [
            {"type": "xpEarned", "value": xp_earned}
        ]
        if total_questions is not None:
            metrics.append({"type": "totalQuestions", "value": total_questions})
        if correct_questions is not None:
            metrics.append({"type": "correctQuestions", "value": correct_questions})

        caliper_event = {
            "@context": "http://purl.imsglobal.org/ctx/caliper/v1p2",
            "id": f"urn:uuid:{run_id}",
            "type": "ActivityEvent",
            "action": "Completed",
            "profile": "TimebackProfile",
            "eventTime": now,
            "actor": {
                "id": f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{user_id}",
                "type": "TimebackUser",
                "email": email
            },
            "object": {
                "id": f"{SENSOR_ID}/activities/{activity_id}",
                "type": "TimebackActivityContext",
                "activity": {
                    "id": activity_id,
                    "name": activity_name
                },
                "course": {
                    "code": course_code
                }
            },
            "generated": {
                "id": f"{API_BASE}/ims/metrics/collections/activity/{run_id}",
                "type": "TimebackActivityMetricsCollection",
                "items": metrics,
                "extensions": {"pctCompleteApp": pct_complete}
            },
            "edApp": SENSOR_ID,
            "extensions": {
                "runId": run_id,
                "courseId": course_code,
                "pipelineHint": "gradebook"  # Hint to run gradebook pipeline
            }
        }

        envelope = {
            "sensor": SENSOR_ID,
            "sendTime": now,
            "dataVersion": "http://purl.imsglobal.org/ctx/caliper/v1p2",
            "data": [caliper_event]
        }

        try:
            resp = requests.post(CALIPER_URL, headers=headers, json=envelope, timeout=30)
            debug.append({
                "step": "2_caliper_event",
                "url": CALIPER_URL,
                "status": resp.status_code,
                "body": resp.text[:500]
            })
            
            if resp.status_code in (200, 201, 204):
                send_json(self, {
                    "status": "success",
                    "method": "caliper_event",
                    "response": resp.json() if resp.text else {},
                    "debug": debug
                })
            else:
                send_json(self, {
                    "status": "error",
                    "message": f"Both methods failed",
                    "debug": debug
                }, 502)
        except Exception as e:
            debug.append({"step": "2_caliper_event", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": str(e),
                "debug": debug
            }, 500)
