"""POST /api/assign-test — Assign a test to a student via PowerPath API.
GET  /api/assign-test?student=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.

The PowerPath API uses the field name "student" (not studentId or userId).
POST requires: { student, subject, grade }
GET requires: ?student=sourcedId
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

    def do_GET(self):
        """List test assignments for a student."""
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        student_id = (params.get("student", params.get("userId", [""]))[0]).strip()

        if not student_id:
            send_json(self, {"error": "Missing student param", "testAssignments": []}, 400)
            return

        headers = api_headers()
        try:
            resp = requests.get(
                f"{API_BASE}/powerpath/test-assignments",
                headers=headers,
                params={"student": student_id},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                send_json(self, data)
            else:
                send_json(self, {"testAssignments": [], "error": f"Status {resp.status_code}"})
        except Exception as e:
            send_json(self, {"testAssignments": [], "error": str(e)})

    def do_DELETE(self):
        """Remove a test assignment."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length else b""
            body = json.loads(raw) if raw else {}

            assignment_id = body.get("assignmentId", "").strip()
            student_id = body.get("student", body.get("studentId", "")).strip()
            subject = body.get("subject", "").strip()
            grade = body.get("grade", "").strip()

            headers = api_headers()
            deleted = False

            # Try DELETE by assignment ID
            if assignment_id:
                try:
                    resp = requests.delete(
                        f"{API_BASE}/powerpath/test-assignments/{assignment_id}",
                        headers=headers, timeout=30,
                    )
                    if resp.status_code in (200, 204):
                        deleted = True
                except Exception:
                    pass

            # Try DELETE by student + subject + grade
            if not deleted and student_id and subject and grade:
                try:
                    resp = requests.delete(
                        f"{API_BASE}/powerpath/test-assignments",
                        headers=headers,
                        json={"student": student_id, "subject": subject, "grade": grade},
                        timeout=30,
                    )
                    if resp.status_code in (200, 204):
                        deleted = True
                except Exception:
                    pass

            send_json(self, {"success": deleted, "message": "Removed" if deleted else "Could not remove"})
        except Exception as e:
            send_json(self, {"success": False, "error": str(e)}, 500)

    def do_POST(self):
        """Assign a test to a student."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length else b""
            if not raw:
                send_json(self, {"error": "Empty body", "success": False}, 400)
                return

            body = json.loads(raw)

            # Accept "student" or "studentId" from frontend, always send "student" to PowerPath
            student_id = (body.get("student") or body.get("studentId") or "").strip()
            subject = body.get("subject", "").strip()
            grade = body.get("grade", "").strip()
            test_type = body.get("type", "").strip()

            if not student_id:
                send_json(self, {"error": "student is required", "success": False}, 400)
                return

            if not subject or not grade:
                send_json(self, {"error": "subject and grade are required", "success": False}, 400)
                return

            headers = api_headers()

            # ── Screening test ────────────────────────────────────
            if test_type == "screening":
                ok, method, resp_data, err = _post(
                    headers,
                    f"{API_BASE}/powerpath/screening/tests/assign",
                    {"student": student_id, "subject": subject, "grade": grade},
                    "screening",
                )
                if not ok:
                    # Fallback: try userId field
                    ok, method, resp_data, err = _post(
                        headers,
                        f"{API_BASE}/powerpath/screening/tests/assign",
                        {"userId": student_id, "subject": subject, "grade": grade},
                        "screening_userId",
                    )
            else:
                # ── Standard test assignment ──────────────────────
                ok, method, resp_data, err = _post(
                    headers,
                    f"{API_BASE}/powerpath/test-assignments",
                    {"student": student_id, "subject": subject, "grade": grade},
                    "test_assignment",
                )

            if ok:
                send_json(self, {
                    "success": True,
                    "method": method,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "response": resp_data,
                })
            else:
                # Return the actual error from PowerPath
                error_msg = err or "Assignment failed"
                send_json(self, {
                    "success": False,
                    "method": method,
                    "message": error_msg,
                    "error": error_msg,
                    "response": resp_data,
                }, 400 if "not enrolled" in (error_msg or "").lower() else 502)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _post(headers, url, payload, method_name):
    """POST to PowerPath. Returns (ok, method, response, error). Retries on timeout.
    Checks BOTH HTTP status code AND response body 'success' field."""
    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            try:
                data = resp.json()
            except Exception:
                data = {"status": resp.status_code}

            # Check HTTP status first
            if resp.status_code not in (200, 201, 204):
                err = data.get("error", data.get("message",
                    data.get("imsx_description", f"Status {resp.status_code}")))
                return False, method_name, data, err

            # ALSO check response body — PowerPath can return 200 with {"success": false}
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
