"""POST /api/powerpath-complete — Complete a lesson via PowerPath reset + finalize.

Body:
  studentId: string (required)
  lessonId: string (required) - courseComponentResource sourcedId
  score: number (0-100)

Flow:
  1. POST /powerpath/resetAttempt - Reset/create a clean attempt
  2. POST /powerpath/finalStudentAssessmentResponse - Finalize with score
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


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

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Step 1: Reset attempt (creates a clean slate for the lesson)
        reset_url = f"{API_BASE}/powerpath/resetAttempt"
        reset_payload = {
            "student": student_id,
            "lesson": lesson_id
        }

        try:
            resp = requests.post(reset_url, headers=headers, json=reset_payload, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(reset_url, headers=headers, json=reset_payload, timeout=30)
            
            debug.append({
                "step": "1_reset_attempt",
                "url": reset_url,
                "payload": reset_payload,
                "status": resp.status_code,
                "body": resp.text[:1000]
            })

            if resp.status_code not in (200, 201):
                # Reset may fail for non-quiz content — proceed to finalize anyway
                pass
            else:
                try:
                    reset_data = resp.json()
                    debug.append({"reset_response": reset_data})
                except:
                    pass

        except Exception as e:
            debug.append({"step": "1_reset_attempt", "error": str(e)})

        # Step 2: Finalize assessment
        finalize_url = f"{API_BASE}/powerpath/finalStudentAssessmentResponse"
        finalize_payload = {
            "student": student_id,
            "lesson": lesson_id,
            "score": score
        }

        try:
            resp = requests.post(finalize_url, headers=headers, json=finalize_payload, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(finalize_url, headers=headers, json=finalize_payload, timeout=30)
            
            debug.append({
                "step": "2_finalize",
                "url": finalize_url,
                "payload": finalize_payload,
                "status": resp.status_code,
                "body": resp.text[:1000]
            })

            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                except:
                    data = {}
                send_json(self, {
                    "status": "success",
                    "response": data,
                    "debug": debug
                })
            else:
                send_json(self, {
                    "status": "error", 
                    "message": f"Finalize failed ({resp.status_code})",
                    "debug": debug
                }, resp.status_code if resp.status_code < 500 else 502)

        except Exception as e:
            debug.append({"step": "2_finalize", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": str(e),
                "debug": debug
            }, 500)
