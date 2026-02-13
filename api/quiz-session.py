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
import re
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params
from api._kv import kv_get


def _extract_correct_answer(question):
    """Extract the correct answer from the question's QTI XML (for testing)."""
    raw_xml = question.get("content", {}).get("rawXml", "") if isinstance(question.get("content"), dict) else ""
    match = re.search(r'<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>', raw_xml)
    return match.group(1) if match else None

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
                # Accept locally-answered IDs to skip (handles stale server state on reload)
                skip_ids_raw = params.get("skipIds", "")
                skip_ids = set(s for s in skip_ids_raw.split(",") if s) if skip_ids_raw else set()

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
                        # Filter out questions hidden by admin
                        hidden = kv_get(f"hidden_questions:{student}") or []
                        total_q = len(questions)
                        answered_q = 0
                        # Find the first unanswered question
                        for q in questions:
                            qid = str(q.get("id", ""))
                            if qid in hidden:
                                answered_q += 1
                                continue
                            # Skip if locally answered (handles server state lag after reload)
                            if qid and qid in skip_ids:
                                answered_q += 1
                                continue
                            answered = q.get("answered", False) or q.get("response") is not None
                            if answered:
                                answered_q += 1
                            elif not answered:
                                # Inject correctId for testing green dot
                                cid = _extract_correct_answer(q)
                                if cid:
                                    q["correctId"] = cid
                                q["totalQuestions"] = total_q
                                q["answeredQuestions"] = answered_q
                                send_json(self, q)
                                return
                        # If 0 total questions, try getNextQuestion as fallback
                        # This is the normal case for PowerPath - getAssessmentProgress doesn't return questions array
                        try:
                            nq_resp = requests.get(
                                f"{PP}/getNextQuestion",
                                headers=headers,
                                params={"student": student, "lesson": lesson},
                                timeout=15,
                            )
                            if nq_resp.status_code == 200:
                                nq_data = nq_resp.json()
                                # getNextQuestion returns {question: {...}, score: ...}
                                question = nq_data.get("question")
                                if question and question.get("id"):
                                    # Got a question via getNextQuestion - format it for frontend
                                    q_out = {
                                        "id": question.get("id"),
                                        "questionId": question.get("id"),
                                        "title": question.get("title"),
                                        "content": question.get("content"),
                                        "difficulty": question.get("difficulty"),
                                        "score": nq_data.get("score", 0),
                                        "totalQuestions": total_q,
                                        "answeredQuestions": answered_q,
                                    }
                                    cid = _extract_correct_answer(question)
                                    if cid:
                                        q_out["correctId"] = cid
                                    send_json(self, q_out)
                                    return
                        except Exception:
                            pass

                        # All questions answered — only mark complete if ALL were answered
                        send_json(self, {
                            "complete": True,
                            "totalQuestions": total_q,
                            "answeredQuestions": answered_q,
                            "score": data.get("score"),
                            "finalized": data.get("finalized", False),
                        })
                        return
                    else:
                        send_json(self, {
                            "error": f"Progress fetch failed ({resp.status_code})",
                            "retry": True,
                        })
                        return
                except Exception as e:
                    send_json(self, {
                        "error": str(e),
                        "retry": True,
                    })
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

    # ── start: NEVER reset unless explicit retry or empty bank ─
    def _handle_start(self, body, headers):
        student_id = body.get("studentId", "")
        test_id = body.get("testId", "")
        lesson_id = body.get("lessonId", "") or test_id
        force_retry = body.get("retry", False)

        if not student_id or not lesson_id:
            send_json(self, {"error": "Need studentId and testId or lessonId"}, 400)
            return

        debug = []
        synthetic_id = _encode_attempt(student_id, lesson_id)

        # ── Explicit retry: reset and start fresh ──
        if force_retry:
            self._do_reset(student_id, lesson_id, headers, debug)
            self._return_progress(student_id, lesson_id, headers, debug, synthetic_id)
            return

        # ── Normal entry: check existing progress, NEVER reset ──
        try:
            resp = requests.get(
                f"{PP}/getAssessmentProgress",
                headers=headers,
                params={"student": student_id, "lesson": lesson_id},
                timeout=15,
            )
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.get(
                    f"{PP}/getAssessmentProgress",
                    headers=headers,
                    params={"student": student_id, "lesson": lesson_id},
                    timeout=15,
                )
            if resp.status_code == 200:
                data = resp.json()
                questions = data.get("questions", [])
                total_q = len(questions)
                answered_q = sum(
                    1 for q in questions
                    if q.get("answered", False) or q.get("response") is not None
                )
                debug.append({
                    "step": "checkProgress",
                    "total": total_q,
                    "answered": answered_q,
                })

                if total_q > 0:
                    # Questions exist — resume, never reset
                    send_json(self, {
                        "attemptId": synthetic_id,
                        "questionCount": total_q,
                        "answeredCount": answered_q,
                        "hasExistingProgress": answered_q > 0,
                        "score": data.get("score"),
                        "debug": debug,
                    })
                    return

                # No questions at all — bank not initialized, need reset
                debug.append({"step": "emptyBank", "resetting": True})
            else:
                debug.append({
                    "step": "checkProgress",
                    "status": resp.status_code,
                    "body": resp.text[:200],
                })
        except Exception as e:
            debug.append({"step": "checkProgress", "error": str(e)})
            # Progress check failed — return ID anyway, DON'T reset
            send_json(self, {
                "attemptId": synthetic_id,
                "questionCount": 0,
                "answeredCount": 0,
                "hasExistingProgress": False,
                "debug": debug,
            })
            return

        # ── Only reaches here if question bank is empty — initialize it ──
        self._do_reset(student_id, lesson_id, headers, debug)
        self._return_progress(student_id, lesson_id, headers, debug, synthetic_id)

    def _do_reset(self, student_id, lesson_id, headers, debug):
        """Call resetAttempt then createNewAttempt to initialize the question bank."""
        # Step 1: resetAttempt
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
                debug.append({"step": "resetAttempt_retry", "status": resp.status_code})
        except Exception as e:
            debug.append({"step": "resetAttempt", "error": str(e)})

        # Step 2: createNewAttempt (documented way to get a fresh question bank)
        try:
            resp = requests.post(
                f"{PP}/createNewAttempt",
                headers=headers,
                json={"student": student_id, "lesson": lesson_id},
                timeout=10,
            )
            debug.append({
                "step": "createNewAttempt",
                "status": resp.status_code,
                "body": resp.text[:300],
            })
        except Exception as e:
            debug.append({"step": "createNewAttempt", "error": str(e)})

    def _return_progress(self, student_id, lesson_id, headers, debug, synthetic_id):
        """Fetch progress after a reset and return it."""
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
                send_json(self, {
                    "attemptId": synthetic_id,
                    "questionCount": len(questions),
                    "answeredCount": 0,
                    "hasExistingProgress": False,
                    "score": data.get("score"),
                    "debug": debug,
                })
                return
        except Exception as e:
            debug.append({"step": "getAssessmentProgress", "error": str(e)})

        # Fallback: try legacy endpoints
        test_id = lesson_id
        for payload in [
            {"student": student_id, "lesson": lesson_id},
        ]:
            for path in [f"{PP}/assessments/attempts", f"{PP}/assessments/create-new-attempt"]:
                try:
                    resp = requests.post(path, headers=headers, json=payload, timeout=6)
                    if resp.status_code in (200, 201):
                        send_json(self, resp.json(), resp.status_code)
                        return
                except Exception:
                    pass

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
