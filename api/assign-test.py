"""POST /api/assign-test — Assign a test via PowerPath API.
GET  /api/assign-test?student=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.

PowerPath base: https://api.alpha-1edtech.ai/powerpath
Auth: existing Cognito creds work (no separate PowerPath token needed)
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json

PP = f"{API_BASE}/powerpath"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs

        params = parse_qs(urlparse(self.path).query)
        sid = (params.get("student", params.get("studentId", params.get("userId", [""])))[0]).strip()

        if not sid:
            send_json(self, {"error": "Missing student param", "testAssignments": []}, 400)
            return

        try:
            headers = api_headers()
            # Try both field names for the query param
            resp = requests.get(f"{PP}/test-assignments", headers=headers, params={"student": sid}, timeout=10)
            if resp.status_code == 200:
                send_json(self, resp.json())
                return
            resp = requests.get(f"{PP}/test-assignments", headers=headers, params={"studentId": sid}, timeout=10)
            if resp.status_code == 200:
                send_json(self, resp.json())
            else:
                send_json(self, {"testAssignments": [], "error": f"Status {resp.status_code}"})
        except Exception as e:
            send_json(self, {"testAssignments": [], "error": str(e)})

    def do_DELETE(self):
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            body = json.loads(raw) if raw else {}
            aid = (body.get("assignmentId") or "").strip()
            headers = api_headers()
            deleted = False

            if aid:
                try:
                    resp = requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=10)
                    if resp.status_code in (200, 204):
                        deleted = True
                except Exception:
                    pass

            send_json(self, {"success": deleted, "message": "Removed" if deleted else "Could not remove"})
        except Exception as e:
            send_json(self, {"success": False, "error": str(e)}, 500)

    def do_POST(self):
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            if not raw:
                send_json(self, {"error": "Empty body", "success": False}, 400)
                return

            body = json.loads(raw)
            sid = (body.get("studentId") or body.get("student") or body.get("userId") or "").strip()
            subject = (body.get("subject") or "").strip()
            grade = (body.get("gradeLevel") or body.get("grade") or "").strip()

            if not sid:
                send_json(self, {"error": "studentId is required", "success": False}, 400)
                return
            if not subject or not grade:
                send_json(self, {"error": "subject and grade are required", "success": False}, 400)
                return

            headers = api_headers()
            errors = []

            # Try multiple field name combos on test-assignments endpoint
            # (API may want student/grade or studentId/gradeLevel)
            for payload in [
                {"student": sid, "subject": subject, "grade": grade},
                {"studentId": sid, "subject": subject, "gradeLevel": grade},
                {"student": sid, "subject": subject, "gradeLevel": grade},
                {"studentId": sid, "subject": subject, "grade": grade},
            ]:
                try:
                    resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=8)
                    if resp.status_code in (200, 201, 204):
                        data = resp.json()
                        if not (isinstance(data, dict) and data.get("success") is False):
                            send_json(self, {
                                "success": True,
                                "message": f"Test assigned ({subject} Grade {grade})",
                                "response": data,
                            })
                            return
                    if resp.status_code not in (422, 400):
                        # Non-validation error — record and stop trying this endpoint
                        errors.append(f"test-assignments: HTTP {resp.status_code}")
                        break
                except Exception as e:
                    errors.append(f"test-assignments: {e}")
                    break

            # Strategy 2: screening endpoint (same field name combos)
            for payload in [
                {"student": sid, "subject": subject, "grade": grade},
                {"studentId": sid, "subject": subject, "gradeLevel": grade},
            ]:
                try:
                    resp = requests.post(f"{PP}/screening/tests/assign", headers=headers, json=payload, timeout=8)
                    if resp.status_code in (200, 201, 204):
                        data = resp.json()
                        if not (isinstance(data, dict) and data.get("success") is False):
                            send_json(self, {
                                "success": True,
                                "message": f"Test assigned ({subject} Grade {grade})",
                                "response": data,
                            })
                            return
                    if resp.status_code not in (422, 400):
                        errors.append(f"screening: HTTP {resp.status_code}")
                        break
                except Exception as e:
                    errors.append(f"screening: {e}")
                    break

            # Strategy 3: two-step (createInternalTest → assign)
            for payload in [
                {"studentId": sid, "subject": subject, "gradeLevel": grade},
                {"student": sid, "subject": subject, "grade": grade},
            ]:
                try:
                    resp = requests.post(f"{PP}/assessments/create-internal-test", headers=headers, json=payload, timeout=8)
                    if resp.status_code in (200, 201):
                        create_data = resp.json()
                        new_id = create_data.get("testId") or create_data.get("id") or ""
                        if new_id:
                            resp2 = requests.post(f"{PP}/test-assignments", headers=headers, json={"studentId": sid, "testId": str(new_id)}, timeout=8)
                            if resp2.status_code in (200, 201, 204):
                                send_json(self, {
                                    "success": True,
                                    "message": f"Test assigned ({subject} Grade {grade})",
                                    "response": resp2.json(),
                                })
                                return
                        elif create_data.get("attemptId") or create_data.get("id"):
                            # createInternalTest itself created the assignment
                            send_json(self, {
                                "success": True,
                                "message": f"Test assigned ({subject} Grade {grade})",
                                "response": create_data,
                            })
                            return
                    if resp.status_code not in (422, 400):
                        errors.append(f"create-internal-test: HTTP {resp.status_code}")
                        break
                except Exception as e:
                    errors.append(f"create-internal-test: {e}")
                    break

            send_json(self, {
                "success": False,
                "error": errors[0] if errors else "All assignment strategies failed",
                "details": errors,
            }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
