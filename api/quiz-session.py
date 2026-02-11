"""POST/GET /api/quiz-session — Manage PowerPath assessment quiz sessions.

Endpoints (via query param 'action'):
  POST ?action=start     — Start attempt: {studentId, testId?, subject?, gradeLevel?}
  GET  ?action=next      — Get next question: {attemptId}
  POST ?action=respond   — Submit response: {attemptId, questionId, response}
  POST ?action=finalize  — Finalize attempt: {attemptId}

PowerPath documented endpoints:
  POST /api/v1/powerpath/new-attempt         { studentId, subject, gradeLevel }
  GET  /api/v1/powerpath/next-question       ?attemptId=xxx
  POST /api/v1/powerpath/update-response     { attemptId, questionId, response }
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


def _pp(method, path, data=None):
    """Make a PowerPath API request. Tries documented paths first.
    Short timeout to stay within Vercel's execution limit."""
    headers = api_headers()

    # Try multiple base path patterns
    bases = [
        f"{API_BASE}/api/v1/powerpath",     # documented path
        f"{API_BASE}/powerpath",             # alternate
    ]

    for base in bases:
        url = f"{base}{path}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=8)
            else:
                resp = requests.post(url, headers=headers, json=data, timeout=8)

            if resp.status_code in (200, 201, 204):
                try:
                    return resp.json(), resp.status_code
                except Exception:
                    return {"status": "ok"}, resp.status_code
            elif resp.status_code != 404:
                try:
                    return resp.json(), resp.status_code
                except Exception:
                    return {"error": resp.text[:200]}, resp.status_code
        except Exception:
            continue

    return None, 0


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

        if action == "next":
            attempt_id = params.get("attemptId", "")
            if not attempt_id:
                send_json(self, {"error": "Need attemptId"}, 400)
                return
            # Try documented endpoint first, then fallback
            data, st = _pp("GET", "/next-question", {"attemptId": attempt_id})
            if not data or st >= 400:
                data, st = _pp("GET", "/assessments/next-question", {"attemptId": attempt_id})
            if data:
                send_json(self, data, st)
            else:
                send_json(self, {"error": "Could not get next question", "complete": True}, 200)

        elif action == "progress":
            student_id = params.get("studentId", "")
            test_id = params.get("testId", "")
            data, st = _pp("GET", "/assessments/progress", {"studentId": student_id, "testId": test_id})
            send_json(self, data or {}, st or 200)

        else:
            send_json(self, {"error": "Unknown action. Use: next, progress"}, 400)

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
        except Exception:
            body = {}

        params = get_query_params(self)
        action = params.get("action", body.get("action", ""))

        if action == "start":
            student_id = body.get("studentId", "")
            test_id = body.get("testId", "")
            subject = body.get("subject", "")
            grade_level = str(body.get("gradeLevel", body.get("grade", "")))

            if not student_id:
                send_json(self, {"error": "Need studentId"}, 400)
                return

            data, st = None, 0

            # Strategy 1: /new-attempt with subject + gradeLevel (documented endpoint)
            if subject and grade_level:
                data, st = _pp("POST", "/new-attempt", {
                    "studentId": student_id,
                    "subject": subject,
                    "gradeLevel": grade_level,
                })
                if data and st < 400:
                    send_json(self, data, st)
                    return

            # Strategy 2: /new-attempt with testId
            if test_id:
                data, st = _pp("POST", "/new-attempt", {
                    "studentId": student_id,
                    "testId": test_id,
                })
                if data and st < 400:
                    send_json(self, data, st)
                    return

            # Strategy 3: /assessments/attempts (alternate path)
            if test_id:
                data, st = _pp("POST", "/assessments/attempts", {
                    "studentId": student_id,
                    "testId": test_id,
                })
                if data and st < 400:
                    send_json(self, data, st)
                    return

            # Strategy 4: create-internal-test then new-attempt
            if subject and grade_level:
                data, st = _pp("POST", "/assessments/create-internal-test", {
                    "studentId": student_id,
                    "subject": subject,
                    "gradeLevel": grade_level,
                })
                if data and st < 400:
                    new_id = ""
                    if isinstance(data, dict):
                        new_id = data.get("testId") or data.get("id") or data.get("attemptId") or ""
                    if data.get("attemptId") or data.get("id"):
                        # Already got an attempt
                        send_json(self, data, st)
                        return
                    if new_id:
                        data2, st2 = _pp("POST", "/new-attempt", {
                            "studentId": student_id,
                            "testId": str(new_id),
                        })
                        if data2 and st2 < 400:
                            send_json(self, data2, st2)
                            return

            send_json(self, data or {"error": "Could not start assessment"}, st if st >= 400 else 422)

        elif action == "respond":
            attempt_id = body.get("attemptId", "")
            question_id = body.get("questionId", "")
            response = body.get("response", "")
            if not attempt_id or not question_id:
                send_json(self, {"error": "Need attemptId, questionId, response"}, 400)
                return

            # Try documented endpoint first
            data, st = _pp("POST", "/update-response", {
                "attemptId": attempt_id,
                "questionId": question_id,
                "response": response,
            })
            if not data or st >= 400:
                data, st = _pp("POST", "/assessments/responses", {
                    "attemptId": attempt_id,
                    "questionId": question_id,
                    "response": response,
                })
            send_json(self, data or {"error": "Failed to submit"}, st or 422)

        elif action == "finalize":
            attempt_id = body.get("attemptId", "")
            if not attempt_id:
                send_json(self, {"error": "Need attemptId"}, 400)
                return
            data, st = _pp("POST", "/assessments/finalize", {"attemptId": attempt_id})
            send_json(self, data or {"status": "finalized"}, st if st and st < 400 else 200)

        else:
            send_json(self, {"error": "Unknown action. Use: start, respond, finalize"}, 400)
