"""POST /api/assign-test — Assign a test via PowerPath API.
GET  /api/assign-test?student=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.

Per the OpenAPI spec at /powerpath/openapi.yaml:
  POST /powerpath/test-assignments requires: { student, subject, grade, testName? }
  GET  /powerpath/test-assignments requires: ?student=sourcedId
  DELETE /powerpath/test-assignments/{id}
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
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        sid = (params.get("student", params.get("studentId", params.get("userId", [""])))[0]).strip()

        if not sid:
            send_json(self, {"error": "Missing student param", "testAssignments": []}, 400)
            return

        try:
            headers = api_headers()
            resp = requests.get(
                f"{API_BASE}/powerpath/test-assignments",
                headers=headers,
                params={"student": sid},
                timeout=10,
            )
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
                    resp = requests.delete(f"{API_BASE}/powerpath/test-assignments/{aid}", headers=headers, timeout=10)
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
            test_name = (body.get("testName") or "").strip()

            if not sid:
                send_json(self, {"error": "student is required", "success": False}, 400)
                return
            if not subject or not grade:
                send_json(self, {"error": "subject and grade are required", "success": False}, 400)
                return

            headers = api_headers()

            # Try multiple URLs and field name combos
            urls = [
                f"{API_BASE}/powerpath/test-assignments",
            ]
            payloads = [
                {"student": sid, "subject": subject, "grade": grade},
                {"studentId": sid, "subject": subject, "gradeLevel": grade},
                {"student": sid, "subject": subject, "gradeLevel": grade},
                {"studentId": sid, "subject": subject, "grade": grade},
            ]
            if test_name:
                for p in payloads:
                    p["testName"] = test_name

            data, ok = None, False
            for url in urls:
                for payload in payloads:
                    try:
                        resp = requests.post(url, headers=headers, json=payload, timeout=6)
                        try:
                            data = resp.json()
                        except Exception:
                            data = {"status": resp.status_code}
                        if resp.status_code in (200, 201, 204):
                            if isinstance(data, dict) and data.get("success") is False:
                                continue
                            ok = True
                            break
                        if resp.status_code in (422, 400):
                            continue  # validation error — try next payload
                        if resp.status_code != 404:
                            break
                    except Exception:
                        continue
                if ok:
                    break

            if ok:
                send_json(self, {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "response": data,
                })
            else:
                err = ""
                if isinstance(data, dict):
                    err = data.get("error") or data.get("message") or data.get("imsx_description") or ""
                send_json(self, {
                    "success": False,
                    "error": err or "Assignment failed",
                    "response": data,
                }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
