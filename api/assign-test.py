"""POST /api/assign-test — Assign a test to a student via PowerPath API.

Accepts two calling conventions:

  1. By lineItemId  (from students.html):
     { studentId, lineItemId }

  2. By subject/grade (from index.html):
     { studentId, subject, grade, type? }

Endpoints used:
  /powerpath/test-assignments       — single test assignment (needs lineItemId or subject+grade)
  /powerpath/screening/tests/assign — screening test (needs userId + subject + grade)
  /powerpath/test-assignments/bulk  — bulk assignments
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
        """GET /api/assign-test?userId=... — List existing test assignments for a student."""
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        user_id = params.get("userId", [""])[0].strip()

        if not user_id:
            send_json(self, {"error": "Missing userId", "assignments": []}, 400)
            return

        headers = api_headers()
        assignments = []
        errors = []

        # Try fetching from PowerPath test-assignments
        for field in ["userId", "studentId", "userSourcedId"]:
            try:
                resp = requests.get(
                    f"{API_BASE}/powerpath/test-assignments",
                    headers=headers,
                    params={field: user_id},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("assignments", data.get("data", data.get("testAssignments", [])))
                    if isinstance(items, list) and items:
                        assignments = items
                        break
            except Exception as e:
                errors.append(str(e))

        # Also try the user-specific path
        if not assignments:
            try:
                resp = requests.get(
                    f"{API_BASE}/powerpath/test-assignments/user/{user_id}",
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("assignments", data.get("data", []))
                    if isinstance(items, list):
                        assignments = items
            except Exception as e:
                errors.append(str(e))

        send_json(self, {
            "assignments": assignments,
            "count": len(assignments),
            "errors": errors if not assignments else [],
        })

    def do_DELETE(self):
        """DELETE /api/assign-test — Remove a test assignment."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length else b""
            if not raw:
                send_json(self, {"error": "Empty request body", "success": False}, 400)
                return

            body = json.loads(raw)
            assignment_id = body.get("assignmentId", "").strip()
            student_id = body.get("studentId", "").strip()
            subject = body.get("subject", "").strip()
            grade = body.get("grade", "").strip()

            headers = api_headers()
            deleted = False
            api_response = None

            # Try DELETE by assignment ID
            if assignment_id:
                for path in [
                    f"/powerpath/test-assignments/{assignment_id}",
                    f"/powerpath/test-assignments",
                ]:
                    try:
                        if path.endswith("test-assignments"):
                            resp = requests.delete(
                                f"{API_BASE}{path}",
                                headers=headers,
                                json={"assignmentId": assignment_id},
                                timeout=30,
                            )
                        else:
                            resp = requests.delete(f"{API_BASE}{path}", headers=headers, timeout=30)

                        if resp.status_code in (200, 204):
                            deleted = True
                            try:
                                api_response = resp.json()
                            except Exception:
                                api_response = {"status": resp.status_code}
                            break
                    except Exception:
                        continue

            # Try DELETE by student + subject + grade
            if not deleted and student_id and subject and grade:
                try:
                    resp = requests.delete(
                        f"{API_BASE}/powerpath/test-assignments",
                        headers=headers,
                        json={"userId": student_id, "subject": subject, "grade": grade},
                        timeout=30,
                    )
                    if resp.status_code in (200, 204):
                        deleted = True
                        try:
                            api_response = resp.json()
                        except Exception:
                            api_response = {"status": resp.status_code}
                except Exception:
                    pass

            if deleted:
                send_json(self, {"success": True, "message": "Assignment removed", "response": api_response})
            else:
                send_json(self, {"success": False, "message": "Could not remove assignment"}, 502)

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length else b""
            if not raw:
                send_json(self, {"error": "Empty request body", "success": False}, 400)
                return

            body = json.loads(raw)

            student_id = body.get("studentId", "").strip()
            line_item_id = body.get("lineItemId", "").strip()
            subject = body.get("subject", "").strip()
            grade = body.get("grade", "").strip()
            test_type = body.get("type", "").strip()  # "screening" | "bulk" | "" (auto)
            bulk_assignments = body.get("assignments", [])

            if not student_id and test_type != "bulk":
                send_json(self, {"error": "studentId is required", "success": False}, 400)
                return

            headers = api_headers()
            applied = False
            method_used = ""
            api_response = None
            api_error = None

            # ── Bulk assignments ──────────────────────────────────
            if test_type == "bulk":
                if not bulk_assignments:
                    send_json(self, {"error": "assignments array is required for bulk", "success": False}, 400)
                    return
                try:
                    resp = requests.post(
                        f"{API_BASE}/powerpath/test-assignments/bulk",
                        headers=headers,
                        json={"assignments": bulk_assignments},
                        timeout=60,
                    )
                    if resp.status_code in (200, 201, 204):
                        applied = True
                        method_used = "powerpath_bulk"
                    try:
                        api_response = resp.json()
                    except Exception:
                        api_response = {"status": resp.status_code}
                    if not applied:
                        api_error = f"Bulk endpoint returned {resp.status_code}"
                except Exception as e:
                    api_error = str(e)

            # ── Explicit screening ────────────────────────────────
            elif test_type == "screening":
                if not subject or not grade:
                    send_json(self, {"error": "subject and grade are required for screening", "success": False}, 400)
                    return
                applied, method_used, api_response, api_error = _try_screening(
                    headers, student_id, subject, grade
                )

            # ── By lineItemId (from students.html) ───────────────
            elif line_item_id:
                # Primary: POST /powerpath/test-assignments with lineItemId
                applied, method_used, api_response, api_error = _try_line_item_assign(
                    headers, student_id, line_item_id
                )

            # ── By subject + grade (from index.html) ─────────────
            elif subject and grade:
                # Try multiple payload shapes — PowerPath may expect userId, studentId, or userSourcedId
                _url = f"{API_BASE}/powerpath/test-assignments"
                for field_name, method_label in [
                    ("userId",         "powerpath_userId"),
                    ("studentId",      "powerpath_studentId"),
                    ("userSourcedId",  "powerpath_userSourcedId"),
                ]:
                    payload = {field_name: student_id, "subject": subject, "grade": grade}
                    applied, method_used, api_response, api_error = _post_assignment(
                        headers, _url, payload, method_label
                    )
                    if applied:
                        break

                # Fallback: screening endpoint (always uses userId)
                if not applied:
                    applied, method_used, api_response, api_error = _try_screening(
                        headers, student_id, subject, grade
                    )

            else:
                send_json(self, {
                    "error": "Need either lineItemId or subject+grade",
                    "success": False,
                }, 400)
                return

            # ── Response ──────────────────────────────────────────
            if applied:
                send_json(self, {
                    "success": True,
                    "applied": True,
                    "method": method_used,
                    "message": f"Test assigned via {method_used}",
                    "response": api_response,
                })
            else:
                send_json(self, {
                    "success": False,
                    "applied": False,
                    "method": method_used,
                    "message": "Test assignment failed",
                    "error": api_error or "PowerPath API did not accept the assignment",
                    "response": api_response,
                }, 502)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON body", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


# ── Helpers ───────────────────────────────────────────────────────────

def _post_assignment(headers, url, payload, method_name):
    """POST to a PowerPath endpoint. Returns (applied, method, response, error).
    Retries once on timeout."""
    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {"status": resp.status_code}

            if resp.status_code in (200, 201, 204):
                return True, method_name, resp_data, None

            error_msg = resp_data.get("error", resp_data.get("message", f"Status {resp.status_code}"))
            return False, method_name, resp_data, error_msg
        except requests.exceptions.Timeout:
            if attempt == 0:
                continue  # retry once
            return False, method_name, None, "Request timed out after 2 attempts (60s each)"
        except Exception as e:
            return False, method_name, None, str(e)
    return False, method_name, None, "Unexpected error"


def _try_line_item_assign(headers, student_id, line_item_id):
    """Try assigning by lineItemId using multiple payload shapes."""
    url = f"{API_BASE}/powerpath/test-assignments"

    # Try with lineItemId
    ok, method, resp, err = _post_assignment(
        headers, url,
        {"studentId": student_id, "lineItemId": line_item_id},
        "powerpath_lineItemId",
    )
    if ok:
        return ok, method, resp, err

    # Try with testId alias
    ok, method, resp, err = _post_assignment(
        headers, url,
        {"studentId": student_id, "testId": line_item_id},
        "powerpath_testId",
    )
    if ok:
        return ok, method, resp, err

    # Try with assessmentId alias
    ok, method, resp, err = _post_assignment(
        headers, url,
        {"studentId": student_id, "assessmentId": line_item_id},
        "powerpath_assessmentId",
    )
    if ok:
        return ok, method, resp, err

    return False, "powerpath_lineItem_all_failed", resp, err


def _try_screening(headers, student_id, subject, grade):
    """Try the screening test assignment endpoint."""
    return _post_assignment(
        headers,
        f"{API_BASE}/powerpath/screening/tests/assign",
        {"userId": student_id, "subject": subject, "grade": grade},
        "powerpath_screening",
    )
