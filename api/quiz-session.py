"""POST/GET /api/quiz-session — PowerPath assessment sessions.

Uses the documented PowerPath endpoints:
  POST /powerpath/resetAttempt                    — reset/create attempt
  GET  /powerpath/getAssessmentProgress           — get questions & progress
  PUT  /powerpath/updateStudentQuestionResponse    — submit a response
  POST /powerpath/finalStudentAssessmentResponse   — finalize the attempt

Actions (frontend-facing):
  POST ?action=start    — {studentId, testId, lessonId}
  GET  ?action=next     — {attemptId}  (synthetic pp::student::lesson)
  POST ?action=respond  — {attemptId, questionId, response}
  POST ?action=finalize — {attemptId}
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params

PP = f"{API_BASE}/powerpath"

# Synthetic attemptId prefix so we can distinguish ours from a real one
_PREFIX = "pp::"


def _encode_attempt(student: str, lesson: str) -> str:
    return f"{_PREFIX}{student}::{lesson}"


def _decode_attempt(attempt_id: str):
    """Return (student, lesson) or (None, None) if not a synthetic ID."""
    if attempt_id.startswith(_PREFIX):
        parts = attempt_id[len(_PREFIX):].split("::", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
    return None, None


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET actions ──────────────────────────────────────────
    def do_GET(self):
        params = get_query_params(self)
        action = params.get("action", "")
        headers = api_headers()

        if action == "next":
            attempt_id = params.get("attemptId", "")
            if not attempt_id:
                send_json(self, {"error": "Need attemptId"}, 400)
                return

            student, lesson = _decode_attempt(attempt_id)
            if student and lesson:
                # Use documented getAssessmentProgress endpoint
                try:
                    resp = requests.get(
                        f"{PP}/getAssessmentProgress",
                        headers=headers,
                        params={"student": student, "lesson": lesson},
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        questions = data.get("questions", [])
                        # Find the first unanswered question
                        for q in questions:
                            answered = q.get("answered", False) or q.get("response") is not None
                            if not answered:
                                send_json(self, q)
                                return
                        # All questions answered
                        send_json(self, {
                            "complete": True,
                            "score": data.get("score"),
                            "finalized": data.get("finalized", False),
                        })
                        return
                    else:
                        send_json(self, {"complete": True, "error": f"Progress fetch failed ({resp.status_code})"})
                        return
                except Exception as e:
                    send_json(self, {"complete": True, "error": str(e)})
                    return
            else:
                # Legacy attemptId — try old endpoint as fallback
                try:
                    resp = requests.get(
                        f"{PP}/assessments/next-question",
                        headers=headers,
                        params={"attemptId": attempt_id},
                        timeout=10,
                    )
                    send_json(self, resp.json() if resp.status_code == 200 else {"complete": True}, 200)
                except Exception as e:
                    send_json(self, {"complete": True, "error": str(e)}, 200)

        elif action == "progress":
            sid = params.get("studentId", "")
            lid = params.get("lessonId", params.get("testId", ""))
            try:
                resp = requests.get(
                    f"{PP}/getAssessmentProgress",
                    headers=headers,
                    params={"student": sid, "lesson": lid},
                    timeout=10,
                )
                send_json(self, resp.json(), resp.status_code)
            except Exception as e:
                send_json(self, {"error": str(e)}, 500)
        else:
            send_json(self, {"error": "Use action=next or action=progress"}, 400)

    # ── POST actions ─────────────────────────────────────────
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
            self._handle_start(body, headers)
        elif action == "respond":
            self._handle_respond(body, headers)
        elif action == "finalize":
            self._handle_finalize(body, headers)
        else:
            send_json(self, {"error": "Use action=start, respond, or finalize"}, 400)

    # ── start: resetAttempt + getAssessmentProgress ──────────
    def _handle_start(self, body, headers):
        student_id = body.get("studentId", "")
        test_id = body.get("testId", "")
        lesson_id = body.get("lessonId", "") or test_id

        if not student_id or not lesson_id:
            send_json(self, {"error": "Need studentId and testId or lessonId"}, 400)
            return

        debug = []

        # Step 1: Reset attempt (creates a clean slate)
        try:
            resp = requests.post(
                f"{PP}/resetAttempt",
                headers=headers,
                json={"student": student_id, "lesson": lesson_id},
                timeout=10,
            )
            debug.append({
                "step": "resetAttempt",
                "status": resp.status_code,
                "body": resp.text[:300],
            })
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(
                    f"{PP}/resetAttempt",
                    headers=headers,
                    json={"student": student_id, "lesson": lesson_id},
                    timeout=10,
                )
        except Exception as e:
            debug.append({"step": "resetAttempt", "error": str(e)})

        # Step 2: Get assessment progress (all questions)
        try:
            resp = requests.get(
                f"{PP}/getAssessmentProgress",
                headers=headers,
                params={"student": student_id, "lesson": lesson_id},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                questions = data.get("questions", [])
                synthetic_id = _encode_attempt(student_id, lesson_id)
                send_json(self, {
                    "attemptId": synthetic_id,
                    "questionCount": len(questions),
                    "score": data.get("score"),
                    "debug": debug,
                })
                return
            else:
                debug.append({
                    "step": "getAssessmentProgress",
                    "status": resp.status_code,
                    "body": resp.text[:300],
                })
        except Exception as e:
            debug.append({"step": "getAssessmentProgress", "error": str(e)})

        # Fallback: try legacy endpoints
        for payload in [
            {"student": student_id, "lesson": lesson_id},
            {"student": student_id, "lesson": test_id} if test_id != lesson_id else None,
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

        # All endpoints failed — frontend will use local assessment
        send_json(self, {
            "error": "Assessment endpoints not available",
            "useLocalAssessment": True,
            "debug": debug,
        }, 422)

    # ── respond: updateStudentQuestionResponse ───────────────
    def _handle_respond(self, body, headers):
        attempt_id = body.get("attemptId", "")
        question_id = body.get("questionId", "")
        response = body.get("response", "")

        if not attempt_id or not question_id:
            send_json(self, {"error": "Need attemptId and questionId"}, 400)
            return

        student, lesson = _decode_attempt(attempt_id)
        if student and lesson:
            # Use documented PUT endpoint
            try:
                resp = requests.put(
                    f"{PP}/updateStudentQuestionResponse",
                    headers=headers,
                    json={
                        "student": student,
                        "lesson": lesson,
                        "question": question_id,
                        "response": response,
                    },
                    timeout=10,
                )
                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.put(
                        f"{PP}/updateStudentQuestionResponse",
                        headers=headers,
                        json={
                            "student": student,
                            "lesson": lesson,
                            "question": question_id,
                            "response": response,
                        },
                        timeout=10,
                    )
                if resp.ok:
                    data = resp.json() if resp.text else {}
                    send_json(self, data, resp.status_code)
                else:
                    send_json(self, {"error": resp.text[:200]}, resp.status_code)
            except Exception as e:
                send_json(self, {"error": str(e)}, 500)
        else:
            # Legacy attemptId — use old endpoint
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

    # ── finalize: finalStudentAssessmentResponse ─────────────
    def _handle_finalize(self, body, headers):
        attempt_id = body.get("attemptId", "")
        if not attempt_id:
            send_json(self, {"error": "Need attemptId"}, 400)
            return

        student, lesson = _decode_attempt(attempt_id)
        if student and lesson:
            # Use documented endpoint
            try:
                resp = requests.post(
                    f"{PP}/finalStudentAssessmentResponse",
                    headers=headers,
                    json={"student": student, "lesson": lesson},
                    timeout=15,
                )
                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.post(
                        f"{PP}/finalStudentAssessmentResponse",
                        headers=headers,
                        json={"student": student, "lesson": lesson},
                        timeout=15,
                    )
                if resp.ok:
                    data = resp.json() if resp.text else {}
                    send_json(self, data)
                else:
                    send_json(self, {
                        "status": "error",
                        "message": f"Finalize failed ({resp.status_code})",
                        "body": resp.text[:300],
                    }, resp.status_code if resp.status_code < 500 else 502)
            except Exception as e:
                send_json(self, {"error": str(e)}, 500)
        else:
            # Legacy attemptId — use old endpoint
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
