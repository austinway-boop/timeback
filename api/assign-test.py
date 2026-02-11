"""POST /api/assign-test — Assign a test via PowerPath API.
GET  /api/assign-test?student=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.

Confirmed working PowerPath endpoints (with existing Cognito creds):
  POST /powerpath/test-assignments    { student, subject, grade }
  GET  /powerpath/test-assignments    ?student=sourcedId
  GET  /powerpath/test-assignments/admin  (all assignments)
  DELETE /powerpath/test-assignments/{id}

Field name: "student" (NOT studentId)
Base URL: https://api.alpha-1edtech.ai/powerpath
Auth: existing Cognito token works
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

            # POST /powerpath/test-assignments { student, subject, grade }
            payload = {"student": sid, "subject": subject, "grade": grade}

            try:
                resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=10)
                try:
                    data = resp.json()
                except Exception:
                    data = {"status": resp.status_code, "body": resp.text[:300]}

                if resp.status_code in (200, 201, 204):
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
                        "error": err or f"HTTP {resp.status_code}",
                        "response": data,
                    }, 422)
            except requests.exceptions.Timeout:
                send_json(self, {"success": False, "error": "Request timed out"}, 504)
            except Exception as e:
                send_json(self, {"success": False, "error": str(e)}, 500)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
