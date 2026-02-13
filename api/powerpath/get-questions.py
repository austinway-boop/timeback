"""GET /api/pp-get-questions — Get questions for a PowerPath lesson.

Query params:
  studentId: string (required)
  lessonId: string (required)
"""

import re
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params
from api._kv import kv_list_get


def extract_correct_answer(question):
    """Extract the correct answer from the question's QTI XML."""
    raw_xml = question.get("content", {}).get("rawXml", "")
    match = re.search(r'<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>', raw_xml)
    return match.group(1) if match else None


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
            resp = requests.get(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers,
                params={"student": student_id, "lesson": lesson_id},
                timeout=15
            )
            
            if resp.status_code != 200:
                send_json(self, {"error": f"API returned {resp.status_code}"}, 502)
                return

            progress = resp.json()
            questions = progress.get("questions", [])
            
            # Simplify question data
            simplified = []
            for q in questions:
                simplified.append({
                    "id": q.get("id"),
                    "index": q.get("index"),
                    "title": q.get("title"),
                    "correctAnswer": extract_correct_answer(q),
                    "answered": q.get("correct") is not None,
                    "isCorrect": q.get("correct", False)
                })

            # Filter out globally hidden and permanently bad questions
            try:
                hidden_ids = set(kv_list_get("globally_hidden_questions"))
                bad_ids = set(kv_list_get("bad_questions"))
                blocked = hidden_ids | bad_ids
                if blocked:
                    simplified = [q for q in simplified if q.get("id") not in blocked]
            except Exception:
                pass  # If KV fails, don't block question loading
            
            send_json(self, {
                "score": progress.get("score"),
                "finalized": progress.get("finalized"),
                "attempt": progress.get("attempt"),
                "totalQuestions": len(questions),
                "questions": simplified
            })
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
