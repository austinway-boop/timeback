"""POST /api/pp-answer-one — Answer ONE question.

Body:
  studentId: string (required)
  lessonId: string (required)
  questionIndex: number (default 0) - which question to answer
  response: string (optional) - answer choice (A, B, C, D). If not provided, uses correct answer.
"""

import json
import re
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


def extract_correct_answer(question):
    """Extract the correct answer from the question's QTI XML."""
    raw_xml = question.get("content", {}).get("rawXml", "")
    match = re.search(r'<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>', raw_xml)
    return match.group(1) if match else "A"


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
        user_response = body.get("response", None)

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        
        # Get questions (use GET, not POST)
        try:
            resp = requests.get(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers, 
                params={"student": student_id, "lesson": lesson_id}, 
                timeout=15
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

        # Determine answer
        correct_answer = extract_correct_answer(q)
        answer = user_response if user_response else correct_answer

        # Answer the question (use PUT, not POST)
        try:
            resp = requests.put(
                f"{API_BASE}/powerpath/updateStudentQuestionResponse",
                headers=headers,
                json={
                    "student": student_id,
                    "lesson": lesson_id,
                    "question": q_id,
                    "response": answer
                },
                timeout=10
            )
            
            send_json(self, {
                "status": "success" if resp.status_code == 200 else "error",
                "questionIndex": q_idx,
                "questionId": q_id,
                "response": answer,
                "correctAnswer": correct_answer,
                "isCorrect": answer == correct_answer,
                "totalQuestions": total,
                "httpStatus": resp.status_code
            })
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
