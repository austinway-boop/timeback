"""POST /api/assign-test — Assign a test to a student via PowerPath API.
GET  /api/assign-test?studentId=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.

Flow (from PowerPath API docs):
  1. assessments.createInternalTest({ studentId, subject, gradeLevel }) → returns testId
  2. testAssignments.create({ studentId, testId }) → creates the assignment
  OR: screening/tests/assign({ studentId, subject, gradeLevel }) → one-shot
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
            send_json(self, {"error": "Missing studentId", "testAssignments": []}, 400)
            return

        try:
            headers = api_headers()
            resp = requests.get(
                f"{API_BASE}/powerpath/test-assignments",
                headers=headers,
                params={"student": student_id},
                timeout=15,
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

            assignment_id = (body.get("assignmentId") or "").strip()
            headers = api_headers()
            deleted = False

            if assignment_id:
                try:
                    resp = requests.delete(
                        f"{API_BASE}/powerpath/test-assignments/{assignment_id}",
                        headers=headers, timeout=15,
                    )
                    if resp.status_code in (200, 204):
                        deleted = True
                except Exception:
                    pass

            if not deleted:
                student_id = (body.get("studentId") or body.get("student") or "").strip()
                subject = (body.get("subject") or "").strip()
                grade_level = (body.get("gradeLevel") or body.get("grade") or "").strip()
                if student_id and subject and grade_level:
                    try:
                        resp = requests.delete(
                            f"{API_BASE}/powerpath/test-assignments",
                            headers=headers,
                            json={"student": student_id, "subject": subject, "grade": grade_level},
                            timeout=15,
                        )
                        if resp.status_code in (200, 204):
                            deleted = True
                    except Exception:
                        pass

            send_json(self, {"success": deleted, "message": "Removed" if deleted else "Could not remove"})
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

            student_id = (body.get("studentId") or body.get("student") or body.get("userId") or "").strip()
            subject = (body.get("subject") or "").strip()
            grade_level = (body.get("gradeLevel") or body.get("grade") or "").strip()
            test_id = (body.get("testId") or body.get("lineItemId") or "").strip()
            due_date = (body.get("dueDate") or "").strip()
            bulk = body.get("assignments", [])

            if not student_id and not bulk:
                send_json(self, {"error": "studentId is required", "success": False}, 400)
                return

            headers = api_headers()
            errors = []

            # ── Bulk ─────────────────────────────────────────
            if bulk:
                normalized = [{"student": a.get("studentId", a.get("student", "")), "testId": a.get("testId", "")} for a in bulk]
                ok, data, err = _post(headers, f"{API_BASE}/powerpath/test-assignments/bulk", {"assignments": normalized})
                if ok:
                    send_json(self, {"success": True, "message": "Bulk assignment complete", "response": data})
                else:
                    errors.append(err)
                    send_json(self, {"success": False, "error": "; ".join(errors), "response": data}, 422)
                return

            # ── By testId ────────────────────────────────────
            if test_id:
                payload = {"student": student_id, "testId": test_id}
                if due_date:
                    payload["dueDate"] = due_date
                ok, data, err = _post(headers, f"{API_BASE}/powerpath/test-assignments", payload)
                if ok:
                    send_json(self, {"success": True, "message": "Test assigned", "response": data})
                else:
                    send_json(self, {"success": False, "error": err, "response": data}, 422)
                return

            # ── By subject + gradeLevel ──────────────────────
            if not subject or not grade_level:
                send_json(self, {"error": "Need subject and grade (or testId)", "success": False}, 400)
                return

            # Strategy 1: POST /powerpath/test-assignments with { student, subject, grade }
            # This is the documented endpoint — field must be "student" not "studentId"
            ok, data, err = _post(
                headers,
                f"{API_BASE}/powerpath/test-assignments",
                {"student": student_id, "subject": subject, "grade": grade_level},
            )
            if ok:
                send_json(self, {"success": True, "message": f"Test assigned ({subject} Grade {grade_level})", "response": data})
                return
            errors.append(f"test-assignments: {err}")

            # Strategy 2: screening/tests/assign with { student, subject, grade }
            ok2, data2, err2 = _post(
                headers,
                f"{API_BASE}/powerpath/screening/tests/assign",
                {"student": student_id, "subject": subject, "grade": grade_level},
            )
            if ok2:
                send_json(self, {"success": True, "message": f"Test assigned ({subject} Grade {grade_level})", "response": data2})
                return
            errors.append(f"screening: {err2}")

            # Strategy 3: screening with userId fallback
            ok3, data3, err3 = _post(
                headers,
                f"{API_BASE}/powerpath/screening/tests/assign",
                {"userId": student_id, "subject": subject, "grade": grade_level},
            )
            if ok3:
                send_json(self, {"success": True, "message": f"Test assigned ({subject} Grade {grade_level})", "response": data3})
                return
            errors.append(f"screening-userId: {err3}")

            # All strategies failed — return 422 (not 502!)
            send_json(self, {
                "success": False,
                "error": errors[0] if errors else "Assignment failed",
                "details": errors,
            }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _post(headers, url, payload):
    """POST to PowerPath. Returns (ok, response_data, error_string).
    Short timeout to avoid Vercel 10s function limit."""
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=8)
        try:
            data = resp.json()
        except Exception:
            data = {"status": resp.status_code, "body": resp.text[:200]}

        if resp.status_code not in (200, 201, 204):
            err = ""
            if isinstance(data, dict):
                err = data.get("error") or data.get("message") or data.get("imsx_description") or ""
            return False, data, err or f"HTTP {resp.status_code}"

        if isinstance(data, dict) and data.get("success") is False:
            err = data.get("error") or data.get("message") or "success=false"
            return False, data, err

        return True, data, None
    except requests.exceptions.Timeout:
        return False, None, "Timed out"
    except requests.exceptions.ConnectionError:
        return False, None, "Connection failed"
    except Exception as e:
        return False, None, str(e)
