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
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        send_json(self, {"error": "Use POST", "success": False}, 405)

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
                # Primary: POST /powerpath/test-assignments with subject+grade
                payload = {"studentId": student_id, "subject": subject, "grade": grade}
                applied, method_used, api_response, api_error = _post_assignment(
                    headers, f"{API_BASE}/powerpath/test-assignments", payload, "powerpath_subject_grade"
                )
                # Fallback: screening endpoint
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
                    "message": "Test assigned successfully",
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
