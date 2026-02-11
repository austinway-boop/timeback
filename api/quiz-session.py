"""POST/GET /api/quiz-session — PowerPath assessment sessions.

Actions:
  POST ?action=start    — {studentId, testId, subject, grade}
  GET  ?action=next     — {attemptId}
  POST ?action=respond  — {attemptId, questionId, response}
  POST ?action=finalize — {attemptId}
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params

PP = f"{API_BASE}/powerpath"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        action = params.get("action", "")
        headers = api_headers()

        if action == "next":
            attempt_id = params.get("attemptId", "")
            if not attempt_id:
                send_json(self, {"error": "Need attemptId"}, 400)
                return
            try:
                resp = requests.get(
                    f"{PP}/assessments/next-question",
                    headers=headers,
                    params={"attemptId": attempt_id},
                    timeout=10,
                )
                send_json(self, resp.json() if resp.status_code == 200 else {"complete": True}, resp.status_code if resp.status_code == 200 else 200)
            except Exception as e:
                send_json(self, {"complete": True, "error": str(e)}, 200)

        elif action == "progress":
            sid = params.get("studentId", "")
            tid = params.get("testId", "")
            try:
                resp = requests.get(f"{PP}/assessments/progress", headers=headers, params={"studentId": sid, "testId": tid}, timeout=10)
                send_json(self, resp.json(), resp.status_code)
            except Exception as e:
                send_json(self, {"error": str(e)}, 500)
        else:
            send_json(self, {"error": "Use action=next or action=progress"}, 400)

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            body = {}

        params = get_query_params(self)
        action = params.get("action", body.get("action", ""))
        headers = api_headers()

        if action == "start":
            student_id = body.get("studentId", "")
            test_id = body.get("testId", "")
            lesson_id = body.get("lessonId", "")
            subject = body.get("subject", "")
            grade = body.get("grade", "")

            if not student_id or not (test_id or lesson_id):
                send_json(self, {"error": "Need studentId and testId or lessonId"}, 400)
                return

            # Try PowerPath REST API with known field name combos
            # (These endpoints may not exist yet — if all 404, frontend shows local assessment)
            for payload in [
                {"student": student_id, "lesson": test_id},
                {"student": student_id, "lesson": lesson_id} if lesson_id else None,
                {"studentId": student_id, "testId": test_id},
            ]:
                if payload is None:
                    continue
                for path in [f"{PP}/assessments/attempts", f"{PP}/assessments/create-new-attempt"]:
                    try:
                        resp = requests.post(path, headers=headers, json=payload, timeout=6)
                        if resp.status_code in (200, 201):
                            send_json(self, resp.json(), resp.status_code)
                            return
                    except Exception:
                        pass

            # PowerPath assessment endpoints not available — return cleanly so frontend uses local assessment
            send_json(self, {"error": "Assessment endpoints not available", "useLocalAssessment": True}, 422)

        elif action == "respond":
            attempt_id = body.get("attemptId", "")
            question_id = body.get("questionId", "")
            response = body.get("response", "")

            if not attempt_id or not question_id:
                send_json(self, {"error": "Need attemptId and questionId"}, 400)
                return

            try:
                resp = requests.post(
                    f"{PP}/assessments/responses",
                    headers=headers,
                    json={"attemptId": attempt_id, "questionId": question_id, "response": response},
                    timeout=10,
                )
                send_json(self, resp.json() if resp.ok else {"error": resp.text[:200]}, resp.status_code)
            except Exception as e:
                send_json(self, {"error": str(e)}, 500)

        elif action == "finalize":
            attempt_id = body.get("attemptId", "")
            if not attempt_id:
                send_json(self, {"error": "Need attemptId"}, 400)
                return
            try:
                resp = requests.post(
                    f"{PP}/assessments/finalize",
                    headers=headers,
                    json={"attemptId": attempt_id},
                    timeout=10,
                )
                send_json(self, resp.json() if resp.ok else {"status": "ok"}, resp.status_code if resp.ok else 200)
            except Exception as e:
                send_json(self, {"error": str(e)}, 500)

        else:
            send_json(self, {"error": "Use action=start, respond, or finalize"}, 400)
