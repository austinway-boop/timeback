"""POST /api/finalize-lesson — Call PowerPath finalStudentAssessmentResponse.

Body:
  studentId: string (required) - student sourcedId
  lessonId: string (required) - lesson sourcedId (e.g. "USHI23-l10-r104084-bank-v1")
  score: number (optional) - score percentage (0-100), included in finalize if provided

Docs: https://docs.timeback.com/beta/api-reference/beyond-ai/powerpath/lesson-mastery/finalize-a-test-assessments
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
        score = body.get("score")  # Optional score passthrough

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Call finalStudentAssessmentResponse
        url = f"{API_BASE}/powerpath/finalStudentAssessmentResponse"
        payload = {
            "student": student_id,
            "lesson": lesson_id
        }
        if score is not None:
            payload["score"] = score

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
            
            debug.append({
                "step": "finalStudentAssessmentResponse",
                "url": url,
                "payload": payload,
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
            debug.append({"step": "finalStudentAssessmentResponse", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": str(e),
                "debug": debug
            }, 500)
