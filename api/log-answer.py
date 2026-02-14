"""POST /api/log-answer — Log a student's question answer to KV.

Fire-and-forget endpoint. Appends to: student_answers:{studentId}:{courseId}
Each entry: { questionId, choiceId, correct, timestamp }

This is a silent observer -- it doesn't affect the quiz flow.
"""

import json
import time
from http.server import BaseHTTPRequestHandler

from api._helpers import send_json
from api._kv import kv_get, kv_set


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"ok": False}, 400)
            return

        student_id = body.get("studentId", "").strip()
        course_id = body.get("courseId", "").strip()
        question_id = body.get("questionId", "").strip()
        choice_id = body.get("choiceId", "")
        correct = bool(body.get("correct", False))

        if not student_id or not question_id:
            send_json(self, {"ok": False}, 400)
            return

        key = f"student_answers:{student_id}:{course_id}" if course_id else f"student_answers:{student_id}:unknown"

        try:
            answers = kv_get(key)
            if not isinstance(answers, list):
                answers = []

            # Check if this question was already answered -- update instead of duplicate
            found = False
            for a in answers:
                if isinstance(a, dict) and a.get("questionId") == question_id:
                    a["choiceId"] = choice_id
                    a["correct"] = correct
                    a["timestamp"] = time.time()
                    found = True
                    break

            if not found:
                answers.append({
                    "questionId": question_id,
                    "choiceId": str(choice_id) if choice_id else "",
                    "correct": correct,
                    "timestamp": time.time(),
                })

            kv_set(key, answers)
            send_json(self, {"ok": True, "count": len(answers)})

        except Exception:
            send_json(self, {"ok": False}, 500)
