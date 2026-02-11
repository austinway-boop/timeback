"""POST /api/assign-test — Assign a test via PowerPath API.
GET  /api/assign-test?student=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.
GET  /api/assign-test?action=placement&student=...&subject=... — Get placement level.

Confirmed working endpoints:
  POST /powerpath/test-assignments    { student, subject, grade }
  GET  /powerpath/test-assignments    ?student=sourcedId
  GET  /powerpath/placement/getCurrentLevel  ?student=...&subject=...
  POST /powerpath/screening/assignTest  { student, testId }
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
        action = params.get("action", [""])[0]
        sid = (params.get("student", params.get("studentId", params.get("userId", [""])))[0]).strip()

        if not sid:
            send_json(self, {"error": "Missing student param", "testAssignments": []}, 400)
            return

        headers = api_headers()

        # Placement check
        if action == "placement":
            subject = params.get("subject", [""])[0].strip()
            if not subject:
                send_json(self, {"error": "Missing subject param"}, 400)
                return
            try:
                resp = requests.get(
                    f"{PP}/placement/getCurrentLevel",
                    headers=headers,
                    params={"student": sid, "subject": subject},
                    timeout=10,
                )
                if resp.status_code == 200:
                    send_json(self, resp.json())
                else:
                    send_json(self, {"error": f"Status {resp.status_code}"})
            except Exception as e:
                send_json(self, {"error": str(e)})
            return

        # List assignments
        try:
            resp = requests.get(f"{PP}/test-assignments", headers=headers, params={"student": sid}, timeout=10)
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
            sid = (body.get("student") or body.get("studentId") or body.get("userId") or "").strip()
            subject = (body.get("subject") or "").strip()
            grade = (body.get("grade") or body.get("gradeLevel") or "").strip()

            if not sid:
                send_json(self, {"error": "student is required", "success": False}, 400)
                return
            if not subject or not grade:
                send_json(self, {"error": "subject and grade are required", "success": False}, 400)
                return

            headers = api_headers()

            # Step 1: Check student placement level
            placement_grade = None
            try:
                pl_resp = requests.get(
                    f"{PP}/placement/getCurrentLevel",
                    headers=headers,
                    params={"student": sid, "subject": subject},
                    timeout=6,
                )
                if pl_resp.status_code == 200:
                    pl_data = pl_resp.json()
                    placement_grade = pl_data.get("gradeLevel") or pl_data.get("grade")
                    if isinstance(placement_grade, dict):
                        placement_grade = placement_grade.get("level") or placement_grade.get("grade")
            except Exception:
                pass

            # Step 2: Try direct test-assignments
            payload = {"student": sid, "subject": subject, "grade": grade}
            resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=10)
            try:
                data = resp.json()
            except Exception:
                data = {"status": resp.status_code}

            if resp.status_code in (200, 201, 204):
                send_json(self, {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "response": data,
                })
                return

            # Step 3: If test-assignments failed, try screening endpoint
            for screen_path in [
                f"{PP}/screening/assignTest",
                f"{PP}/screening/tests/assign",
            ]:
                try:
                    screen_resp = requests.post(
                        screen_path, headers=headers,
                        json={"student": sid, "subject": subject, "grade": grade},
                        timeout=6,
                    )
                    if screen_resp.status_code in (200, 201, 204):
                        send_json(self, {
                            "success": True,
                            "message": f"Test assigned via screening ({subject} Grade {grade})",
                            "response": screen_resp.json(),
                        })
                        return
                except Exception:
                    pass

            # All failed — build helpful error message
            err = ""
            if isinstance(data, dict):
                err = data.get("imsx_description") or data.get("error") or data.get("message") or ""

            # Check if it's a placement level mismatch
            hint = ""
            if err == "An unexpected error occurred" and placement_grade is not None:
                try:
                    req_grade = int(grade)
                    pl_grade = int(placement_grade)
                    if req_grade > pl_grade:
                        hint = f" Student is placed at Grade {pl_grade} in {subject}, but Grade {grade} was requested. Try assigning Grade {pl_grade} instead."
                except (ValueError, TypeError):
                    pass

            send_json(self, {
                "success": False,
                "error": (err or f"HTTP {resp.status_code}") + hint,
                "placementGrade": placement_grade,
                "requestedGrade": grade,
                "response": data,
            }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
