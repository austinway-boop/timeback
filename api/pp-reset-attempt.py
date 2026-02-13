"""POST /api/pp-reset-attempt — Reset a PowerPath lesson attempt.

Body:
  studentId: string (required)
  lessonId: string (required) - courseComponentResource sourcedId
"""

import json
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
        lesson_id = body.get("lessonId", "")

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        url = f"{API_BASE}/powerpath/resetAttempt"
        payload = {
            "student": student_id,
            "lesson": lesson_id
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if resp.status_code in (200, 201):
                send_json(self, {
                    "status": "success",
                    "response": resp.json() if resp.text else {}
                })
            else:
                send_json(self, {
                    "status": "error",
                    "httpStatus": resp.status_code,
                    "body": resp.text[:500]
                }, resp.status_code if resp.status_code < 500 else 502)

        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
