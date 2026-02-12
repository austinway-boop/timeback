"""POST /api/pp-answer-one — Answer ONE question correctly.

Body:
  studentId: string (required)
  lessonId: string (required)
  questionIndex: number (default 0) - which question to answer
  correct: boolean (default true) - whether answer is correct
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
        q_idx = body.get("questionIndex", 0)
        is_correct = body.get("correct", True)

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        
        # Get questions
        try:
            resp = requests.post(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers, 
                json={"student": student_id, "lesson": lesson_id}, 
                timeout=8
            )
            if resp.status_code != 200:
                send_json(self, {"error": f"getAssessmentProgress failed: {resp.status_code}"}, 502)
                return
            progress = resp.json()
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
            return

        questions = progress.get("questions", [])
        total = len(questions)
        
        if q_idx >= total:
            send_json(self, {
                "error": "questionIndex out of range",
                "totalQuestions": total,
                "questionIndex": q_idx
            }, 400)
            return

        q = questions[q_idx]
        q_id = q.get("id", "")
        
        if not q_id:
            send_json(self, {"error": "Question has no ID"}, 400)
            return

        # Answer the question
        try:
            resp = requests.post(
                f"{API_BASE}/powerpath/updateStudentQuestionResponse",
                headers=headers,
                json={
                    "student": student_id,
                    "lesson": lesson_id,
                    "question": q_id,
                    "answered": True,
                    "correct": is_correct
                },
                timeout=8
            )
            
            send_json(self, {
                "status": "success" if resp.status_code in (200, 201) else "error",
                "questionIndex": q_idx,
                "questionId": q_id,
                "correct": is_correct,
                "totalQuestions": total,
                "httpStatus": resp.status_code
            })
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
