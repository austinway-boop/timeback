"""POST /api/assign-test — Assign a test to a student via PowerPath API.
GET  /api/assign-test?studentId=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.

PowerPath field names (from API docs):
  testAssignments.create  → { studentId, testId, dueDate }
  screening/tests/assign  → { studentId, subject, gradeLevel }
  testAssignments.bulk    → { assignments: [{ studentId, testId }] }
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET: list test assignments for a student ──────────────
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs

        params = parse_qs(urlparse(self.path).query)
        student_id = (
            params.get("studentId", params.get("student", params.get("userId", [""])))[0]
        ).strip()

        if not student_id:
            send_json(self, {"error": "Missing studentId param", "testAssignments": []}, 400)
            return

        headers = api_headers()
        try:
            resp = requests.get(
                f"{API_BASE}/powerpath/test-assignments",
                headers=headers,
                params={"studentId": student_id},
                timeout=30,
            )
            if resp.status_code == 200:
                send_json(self, resp.json())
            else:
                send_json(self, {"testAssignments": [], "error": f"Status {resp.status_code}"})
        except Exception as e:
            send_json(self, {"testAssignments": [], "error": str(e)})

    # ── DELETE: remove a test assignment ──────────────────────
    def do_DELETE(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length else b""
            body = json.loads(raw) if raw else {}

            assignment_id = body.get("assignmentId", "").strip()
            headers = api_headers()
            deleted = False

            if assignment_id:
                try:
                    resp = requests.delete(
                        f"{API_BASE}/powerpath/test-assignments/{assignment_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code in (200, 204):
                        deleted = True
                except Exception:
                    pass

            # Fallback: try with body params
            if not deleted:
                student_id = body.get("studentId", body.get("student", "")).strip()
                subject = body.get("subject", "").strip()
                grade_level = body.get("gradeLevel", body.get("grade", "")).strip()
                if student_id and subject and grade_level:
                    try:
                        resp = requests.delete(
                            f"{API_BASE}/powerpath/test-assignments",
                            headers=headers,
                            json={
                                "studentId": student_id,
                                "subject": subject,
                                "gradeLevel": grade_level,
                            },
                            timeout=30,
                        )
                        if resp.status_code in (200, 204):
                            deleted = True
                    except Exception:
                        pass

            send_json(
                self,
                {"success": deleted, "message": "Removed" if deleted else "Could not remove"},
            )
        except Exception as e:
            send_json(self, {"success": False, "error": str(e)}, 500)

    # ── POST: assign a test ──────────────────────────────────
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length else b""
            if not raw:
                send_json(self, {"error": "Empty body", "success": False}, 400)
                return

            body = json.loads(raw)

            # Normalize: accept multiple field name conventions from frontends
            student_id = (
                body.get("studentId")
                or body.get("student")
                or body.get("userId")
                or ""
            ).strip()
            subject = body.get("subject", "").strip()
            grade_level = body.get("gradeLevel", body.get("grade", "")).strip()
            test_id = body.get("testId", body.get("lineItemId", "")).strip()
            test_type = body.get("type", "").strip()
            due_date = body.get("dueDate", "").strip()
            bulk = body.get("assignments", [])

            if not student_id and not bulk:
                send_json(self, {"error": "studentId is required", "success": False}, 400)
                return

            headers = api_headers()

            # ── Bulk assignment ───────────────────────────────
            if bulk:
                normalized = [
                    {"studentId": a.get("studentId", ""), "testId": a.get("testId", "")}
                    for a in bulk
                ]
                ok, method, resp_data, err = _post(
                    headers,
                    f"{API_BASE}/powerpath/test-assignments/bulk",
                    {"assignments": normalized},
                    "bulk",
                )
                return _respond(self, ok, method, resp_data, err, subject, grade_level)

            # ── Assignment by testId (from students.html) ─────
            if test_id:
                payload = {"studentId": student_id, "testId": test_id}
                if due_date:
                    payload["dueDate"] = due_date

                ok, method, resp_data, err = _post(
                    headers,
                    f"{API_BASE}/powerpath/test-assignments",
                    payload,
                    "test_assignment_by_id",
                )
                return _respond(self, ok, method, resp_data, err, subject, grade_level)

            # ── Assignment by subject + gradeLevel ────────────
            if not subject or not grade_level:
                send_json(
                    self,
                    {"error": "subject and grade are required (or provide testId)", "success": False},
                    400,
                )
                return

            # Primary: screening/tests/assign (creates + assigns in one call)
            ok, method, resp_data, err = _post(
                headers,
                f"{API_BASE}/powerpath/screening/tests/assign",
                {"studentId": student_id, "subject": subject, "gradeLevel": grade_level},
                "screening",
            )

            # Fallback 1: try with different field names
            if not ok:
                ok, method, resp_data, err = _post(
                    headers,
                    f"{API_BASE}/powerpath/screening/tests/assign",
                    {"userId": student_id, "subject": subject, "grade": grade_level},
                    "screening_alt",
                )

            # Fallback 2: create internal test + assign
            if not ok:
                ok, method, resp_data, err = _post(
                    headers,
                    f"{API_BASE}/powerpath/test-assignments",
                    {"studentId": student_id, "subject": subject, "gradeLevel": grade_level},
                    "test_assignment_subject",
                )

            return _respond(self, ok, method, resp_data, err, subject, grade_level)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


# ── Helpers ───────────────────────────────────────────────────

def _post(headers, url, payload, method_name):
    """POST to PowerPath. Returns (ok, method, response_data, error).
    Retries once on timeout. Checks both HTTP status and response body."""
    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            try:
                data = resp.json()
            except Exception:
                data = {"status": resp.status_code}

            if resp.status_code not in (200, 201, 204):
                err = data.get("error", data.get("message",
                    data.get("imsx_description", f"Status {resp.status_code}")))
                return False, method_name, data, err

            # PowerPath can return 200 with {"success": false}
            if isinstance(data, dict) and data.get("success") is False:
                err = data.get("error", data.get("message", "API returned success=false"))
                return False, method_name, data, err

            return True, method_name, data, None
        except requests.exceptions.Timeout:
            if attempt == 0:
                continue
            return False, method_name, None, "Request timed out"
        except Exception as e:
            return False, method_name, None, str(e)
    return False, method_name, None, "Unexpected error"


def _respond(handler, ok, method, resp_data, err, subject, grade_level):
    """Send the final response back to the frontend."""
    if ok:
        msg = "Test assigned successfully"
        if subject and grade_level:
            msg = f"Test assigned ({subject} Grade {grade_level})"
        send_json(handler, {
            "success": True,
            "method": method,
            "message": msg,
            "response": resp_data,
        })
    else:
        error_msg = err or "Assignment failed"
        status = 400 if "not enrolled" in (error_msg or "").lower() else 502
        send_json(handler, {
            "success": False,
            "method": method,
            "message": error_msg,
            "error": error_msg,
            "response": resp_data,
        }, status)
