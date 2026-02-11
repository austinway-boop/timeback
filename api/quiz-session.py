"""POST/GET /api/quiz-session — PowerPath assessment sessions.

Flow (from API docs):
  1. POST  createNewAttempt       { studentId, testId }     → { attemptId }
  2. GET   getNextQuestion        { attemptId }             → { question with QTI content }
  3. POST  updateStudentQuestionResponse  { attemptId, questionId, response }
  4. POST  finalStudentAssessmentResponse { attemptId }

The testId IS the PowerPath resource ID (e.g. HUMG20-r104435-bank-v1).
PowerPath returns QTI content embedded in getNextQuestion responses.
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


def _try_post(headers, paths, payload):
    """Try POSTing to multiple URL paths, return first success."""
    for url in paths:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=8)
            try:
                data = resp.json()
            except Exception:
                data = {"status": resp.status_code}
            if resp.status_code in (200, 201, 204):
                return data, resp.status_code
            if resp.status_code != 404:
                return data, resp.status_code
        except Exception:
            continue
    return None, 0


def _try_get(headers, paths, params):
    """Try GETting from multiple URL paths, return first success."""
    for url in paths:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=8)
            try:
                data = resp.json()
            except Exception:
                data = {"status": resp.status_code}
            if resp.status_code in (200, 201, 204):
                return data, resp.status_code
            if resp.status_code != 404:
                return data, resp.status_code
        except Exception:
            continue
    return None, 0


# All plausible base paths for PowerPath assessment endpoints
_BASES = [
    f"{API_BASE}/powerpath/assessments",
    f"{API_BASE}/api/v1/powerpath/assessments",
    f"{API_BASE}/powerpath",
    f"{API_BASE}/api/v1/powerpath",
]


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

            headers = api_headers()
            # getNextQuestion — try multiple path patterns
            urls = []
            for base in _BASES:
                urls.extend([
                    f"{base}/get-next-question",
                    f"{base}/getNextQuestion",
                    f"{base}/next-question",
                ])
            data, st = _try_get(headers, urls, {"attemptId": attempt_id})
            if data and st < 400:
                send_json(self, data, st)
            else:
                send_json(self, data or {"complete": True}, st if st and st < 400 else 200)

        elif action == "progress":
            headers = api_headers()
            student_id = params.get("studentId", "")
            test_id = params.get("testId", "")
            urls = [f"{base}/progress" for base in _BASES]
            data, st = _try_get(headers, urls, {"studentId": student_id, "testId": test_id})
            send_json(self, data or {}, st or 200)

        else:
            send_json(self, {"error": "Unknown GET action"}, 400)

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
            if not student_id:
                send_json(self, {"error": "Need studentId"}, 400)
                return
            if not test_id:
                send_json(self, {"error": "Need testId"}, 400)
                return

            headers = api_headers()
            # PowerPath API requires field names: "student" and "lesson" (not studentId/testId)
            payload = {"student": student_id, "lesson": test_id}

            # createNewAttempt — try multiple path patterns
            urls = []
            for base in _BASES:
                urls.extend([
                    f"{base}/create-new-attempt",
                    f"{base}/createNewAttempt",
                    f"{base}/new-attempt",
                    f"{base}/attempts",
                ])
            data, st = _try_post(headers, urls, payload)

            # If "student"/"lesson" failed, retry with alternate field names
            if not data or st >= 400:
                alt_payload = {"studentId": student_id, "testId": test_id}
                data, st = _try_post(headers, urls, alt_payload)

            if data and st < 400:
                send_json(self, data, st)
            else:
                send_json(self, data or {"error": "Could not create attempt"}, st if st >= 400 else 422)

        elif action == "respond":
            attempt_id = body.get("attemptId", "")
            question_id = body.get("questionId", "")
            response = body.get("response", "")
            if not attempt_id or not question_id:
                send_json(self, {"error": "Need attemptId and questionId"}, 400)
                return

            headers = api_headers()
            payload = {"attemptId": attempt_id, "questionId": question_id, "response": response}

            # updateStudentQuestionResponse
            urls = []
            for base in _BASES:
                urls.extend([
                    f"{base}/update-student-question-response",
                    f"{base}/updateStudentQuestionResponse",
                    f"{base}/update-response",
                    f"{base}/responses",
                ])
            data, st = _try_post(headers, urls, payload)
            send_json(self, data or {"error": "Failed to submit"}, st or 422)

        elif action == "finalize":
            attempt_id = body.get("attemptId", "")
            if not attempt_id:
                send_json(self, {"error": "Need attemptId"}, 400)
                return

            headers = api_headers()
            payload = {"attemptId": attempt_id}

            # finalStudentAssessmentResponse
            urls = []
            for base in _BASES:
                urls.extend([
                    f"{base}/final-student-assessment-response",
                    f"{base}/finalStudentAssessmentResponse",
                    f"{base}/finalize",
                ])
            data, st = _try_post(headers, urls, payload)
            send_json(self, data or {"status": "finalized"}, st if st and st < 400 else 200)

        else:
            send_json(self, {"error": "Unknown POST action"}, 400)
