"""GET /api/pp-get-questions — Get question IDs for a lesson.

Query params:
  lessonId: string (required)
  studentId: string (required)
"""

from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        student_id = params.get("studentId", "")
        lesson_id = params.get("lessonId", "")

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
                send_json(self, {"error": f"API failed: {resp.status_code}"}, 502)
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
