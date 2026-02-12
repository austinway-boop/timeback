"""POST /api/pp-get-questions — Get question IDs for a lesson.

Body:
  lessonId: string (required)
  studentId: string (required)
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
        
        try:
            resp = requests.post(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers,
                json={"student": student_id, "lesson": lesson_id},
                timeout=15
            )
            
            if resp.status_code != 200:
                send_json(self, {"error": f"API failed: {resp.status_code}", "body": resp.text[:200]}, 502)
                return
                
            progress = resp.json()
            questions = progress.get("questions", [])
            
            # Return just the IDs
            question_ids = [q.get("id", "") for q in questions if q.get("id")]
            
            send_json(self, {
                "totalQuestions": len(question_ids),
                "finalized": progress.get("finalized", False),
                "score": progress.get("score", 0),
                "questionIds": question_ids
            })
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
