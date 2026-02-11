"""POST/GET /api/quiz-session — Manage PowerPath assessment quiz sessions.

Endpoints (via query param 'action'):
  POST ?action=start     — Start attempt: {studentId, testId}
  GET  ?action=next      — Get next question: {attemptId}
  POST ?action=respond   — Submit response: {attemptId, questionId, response}
  POST ?action=finalize  — Finalize attempt: {attemptId}
  GET  ?action=progress  — Get progress: {studentId, testId}
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params

# Try multiple base URLs for PowerPath
PP_BASES = [
    f"{API_BASE}/powerpath",
    "https://api.timeback.dev/powerpath",
]


def _pp_request(method, path, data=None):
    """Make a PowerPath API request, trying multiple base URLs."""
    headers = api_headers()
    for base in PP_BASES:
        url = f"{base}{path}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=30)
            else:
                resp = requests.post(url, headers=headers, json=data, timeout=30)

            if resp.status_code in (200, 201, 204):
                try:
                    return resp.json(), resp.status_code
                except Exception:
                    return {"status": "ok"}, resp.status_code
            elif resp.status_code != 404:
                # Non-404 error - return it
                try:
                    return resp.json(), resp.status_code
                except Exception:
                    return {"error": resp.text[:300]}, resp.status_code
        except Exception:
            continue

    return {"error": "PowerPath API unreachable"}, 503


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
            data, status = _pp_request("GET", f"/assessments/next-question", {"attemptId": attempt_id})
            send_json(self, data, status)

        elif action == "progress":
            student_id = params.get("studentId", "")
            test_id = params.get("testId", "")
            data, status = _pp_request("GET", "/assessments/progress", {"studentId": student_id, "testId": test_id})
            send_json(self, data, status)

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
            if not student_id or not test_id:
                send_json(self, {"error": "Need studentId and testId"}, 400)
                return
            data, status = _pp_request("POST", "/assessments/attempts", {"studentId": student_id, "testId": test_id})
            send_json(self, data, status)

        elif action == "respond":
            attempt_id = body.get("attemptId", "")
            question_id = body.get("questionId", "")
            response = body.get("response", "")
            if not attempt_id or not question_id:
                send_json(self, {"error": "Need attemptId, questionId, response"}, 400)
                return
            data, status = _pp_request("POST", "/assessments/responses", {
                "attemptId": attempt_id,
                "questionId": question_id,
                "response": response,
            })
            send_json(self, data, status)

        elif action == "finalize":
            attempt_id = body.get("attemptId", "")
            if not attempt_id:
                send_json(self, {"error": "Need attemptId"}, 400)
                return
            data, status = _pp_request("POST", "/assessments/finalize", {"attemptId": attempt_id})
            send_json(self, data, status)

        else:
            send_json(self, {"error": "Unknown action. Use: start, respond, finalize"}, 400)
