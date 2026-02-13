"""POST /api/pp-answer-batch — Answer a batch of questions correctly.

Body:
  studentId: string (required)
  lessonId: string (required)
  startIndex: number (default 0) - which question to start from
  batchSize: number (default 5) - how many questions to answer
  finalize: boolean (default false) - finalize after answering
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
        start_idx = body.get("startIndex", 0)
        batch_size = body.get("batchSize", 5)
        do_finalize = body.get("finalize", False)

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        
        # Get questions
        progress_url = f"{API_BASE}/powerpath/getAssessmentProgress"
        try:
            resp = requests.post(progress_url, headers=headers, 
                               json={"student": student_id, "lesson": lesson_id}, timeout=15)
            if resp.status_code != 200:
                send_json(self, {"error": f"getAssessmentProgress failed: {resp.status_code}"}, 502)
                return
            progress = resp.json()
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
            return

        questions = progress.get("questions", [])
        total = len(questions)
        
        # Answer batch
        answered = 0
        end_idx = min(start_idx + batch_size, total)
        
        for i in range(start_idx, end_idx):
            q = questions[i]
            q_id = q.get("id", "")
            if not q_id:
                continue
            try:
                resp = requests.post(
                    f"{API_BASE}/powerpath/updateStudentQuestionResponse",
                    headers=headers,
                    json={
                        "student": student_id,
                        "lesson": lesson_id,
                        "question": q_id,
                        "answered": True,
                        "correct": True
                    },
                    timeout=8
                )
                if resp.status_code in (200, 201):
                    answered += 1
            except:
                pass

        result = {
            "totalQuestions": total,
            "startIndex": start_idx,
            "endIndex": end_idx,
            "answered": answered,
            "remaining": total - end_idx,
            "allAnswered": end_idx >= total
        }

        # Finalize if requested and all answered
        if do_finalize and end_idx >= total:
            try:
                resp = requests.post(
                    f"{API_BASE}/powerpath/finalStudentAssessmentResponse",
                    headers=headers,
                    json={"student": student_id, "lesson": lesson_id},
                    timeout=15
                )
                result["finalized"] = resp.status_code in (200, 201)
                if resp.status_code in (200, 201):
                    result["finalizeResponse"] = resp.json() if resp.text else {}
            except Exception as e:
                result["finalizeError"] = str(e)

        send_json(self, result)
