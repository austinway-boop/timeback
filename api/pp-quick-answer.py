"""POST /api/pp-quick-answer — Answer a question by ID (no progress lookup).

Body:
  studentId: string (required)
  lessonId: string (required)
  questionId: string (required) - exact question ID
  correct: boolean (default true)
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
        question_id = body.get("questionId", "")
        is_correct = body.get("correct", True)

        if not student_id or not lesson_id or not question_id:
            send_json(self, {"error": "Missing required fields"}, 400)
            return

        headers = api_headers()
        
        try:
            resp = requests.post(
                f"{API_BASE}/powerpath/updateStudentQuestionResponse",
                headers=headers,
                json={
                    "student": student_id,
                    "lesson": lesson_id,
                    "question": question_id,
                    "answered": True,
                    "correct": is_correct
                },
                timeout=8
            )
            
            send_json(self, {
                "status": "success" if resp.status_code in (200, 201) else "error",
                "questionId": question_id,
                "correct": is_correct,
                "httpStatus": resp.status_code
            })
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
