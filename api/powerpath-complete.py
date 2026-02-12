"""POST /api/powerpath-complete — Complete a lesson via PowerPath.

For quiz/MCQ content: reset + finalize assessment
For video/article content: record completion via Caliper event

Body:
  studentId: string (required)
  lessonId: string (required) - courseComponentResource sourcedId
  score: number (0-100, default 100)
  contentType: string (optional) - "quiz", "video", "article". Auto-detected if not provided.
  email: string (optional) - needed for Caliper events
  courseName: string (optional) - for activity recording
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

        student_id = body.get("studentId", "")
        lesson_id = body.get("lessonId", "")
        score = body.get("score", 100)
        content_type = body.get("contentType", "").lower()
        email = body.get("email", "")
        course_name = body.get("courseName", "")

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Try quiz completion first (works for MCQ/test content)
        quiz_success = False
        xp_earned = 0
        final_score = None
        
        # Step 1: Reset attempt (creates a clean slate for the lesson)
        try:
            resp = requests.post(
                f"{API_BASE}/powerpath/resetAttempt",
                headers=headers,
                json={"student": student_id, "lesson": lesson_id},
                timeout=15
            )
            debug.append({
                "step": "1_reset_attempt",
                "status": resp.status_code,
                "body": resp.text[:200]
            })
        except Exception as e:
            debug.append({"step": "1_reset_attempt", "error": str(e)})

        # Step 2: Finalize assessment
        try:
            resp = requests.post(
                f"{API_BASE}/powerpath/finalStudentAssessmentResponse",
                headers=headers,
                json={"student": student_id, "lesson": lesson_id, "score": score},
                timeout=15
            )
            debug.append({
                "step": "2_finalize",
                "status": resp.status_code,
                "body": resp.text[:300]
            })
            
            if resp.status_code == 200:
                quiz_success = True
                data = resp.json()
                # Get XP from finalize response or fetch it
        except Exception as e:
            debug.append({"step": "2_finalize", "error": str(e)})

        # Step 3: Get final progress to extract XP
        if quiz_success:
            try:
                resp = requests.get(
                    f"{API_BASE}/powerpath/getAssessmentProgress",
                    headers=headers,
                    params={"student": student_id, "lesson": lesson_id},
                    timeout=10
                )
                if resp.status_code == 200:
                    progress = resp.json()
                    xp_earned = progress.get("xp", 0)
                    final_score = progress.get("score", score)
                    debug.append({
                        "step": "3_get_progress",
                        "xp": xp_earned,
                        "score": final_score,
                        "finalized": progress.get("finalized")
                    })
            except Exception as e:
                debug.append({"step": "3_get_progress", "error": str(e)})

        # If quiz finalize failed (e.g., video/article content), send Caliper event
        if not quiz_success and email:
            try:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                run_id = str(uuid.uuid4())
                
                caliper_event = {
                    "@context": "http://purl.imsglobal.org/ctx/caliper/v1p2",
                    "id": f"urn:uuid:{run_id}",
                    "type": "ActivityEvent",
                    "action": "Completed",
                    "profile": "TimebackProfile",
                    "eventTime": now,
                    "actor": {
                        "id": f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{student_id}",
                        "type": "TimebackUser",
                        "email": email
                    },
                    "object": {
                        "id": f"{SENSOR_ID}/activities/{lesson_id}",
                        "type": "TimebackActivityContext",
                        "subject": "Social Studies",
                        "app": {"name": "AlphaLearn"},
                        "activity": {
                            "id": f"{SENSOR_ID}/activities/{lesson_id}",
                            "name": lesson_id
                        },
                        "course": {
                            "code": course_name or lesson_id.split("-")[0],
                            "name": course_name or ""
                        },
                        "process": True
                    },
                    "generated": {
                        "id": f"{API_BASE}/ims/metrics/collections/activity/{run_id}",
                        "type": "TimebackActivityMetricsCollection",
                        "items": [
                            {"type": "xpEarned", "value": 0},
                            {"type": "pctComplete", "value": 100}
                        ],
                        "extensions": {"pctCompleteApp": 100}
                    },
                    "edApp": SENSOR_ID
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
                debug.append({
                    "step": "caliper_fallback",
                    "status": resp.status_code,
                    "body": resp.text[:200]
                })
            except Exception as e:
                debug.append({"step": "caliper_fallback", "error": str(e)})

        send_json(self, {
            "status": "success" if quiz_success else "partial",
            "quizFinalized": quiz_success,
            "xpEarned": xp_earned,
            "finalScore": final_score,
            "debug": debug
        })
