"""PowerPath test assignment + placement API proxy.

Endpoints:
  POST /powerpath/test-assignments                  — Assign test { student, subject, grade }
  GET  /powerpath/test-assignments?student={id}     — Student assignments
  GET  /powerpath/test-assignments/admin             — All assignments (admin)
  GET  /powerpath/test-assignments/{id}              — Single assignment
  DEL  /powerpath/test-assignments/{id}              — Delete assignment
  GET  /powerpath/placement/subjects                 — All placement subjects
  GET  /powerpath/placement/getCurrentLevel          — Current level
  GET  /powerpath/placement/getSubjectProgress       — Progress
  POST /powerpath/placement/resetUserPlacement       — Reset placement
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
        sid = (params.get("student", params.get("studentId", [""]))  [0]).strip()
        subject = params.get("subject", [""])[0].strip()

        headers = api_headers()

        if action == "placement":
            if not sid or not subject:
                send_json(self, {"error": "Need student and subject params"}, 400)
                return
            _proxy_get(self, headers, f"{PP}/placement/getCurrentLevel", {"student": sid, "subject": subject})
            return

        if action == "progress":
            if not sid or not subject:
                send_json(self, {"error": "Need student and subject params"}, 400)
                return
            _proxy_get(self, headers, f"{PP}/placement/getSubjectProgress", {"student": sid, "subject": subject})
            return

        if action == "subjects":
            _proxy_get(self, headers, f"{PP}/placement/subjects", {})
            return

        if action == "admin":
            _proxy_get(self, headers, f"{PP}/test-assignments/admin", {})
            return

        if action == "get":
            aid = params.get("id", [""])[0].strip()
            if not aid:
                send_json(self, {"error": "Need id param"}, 400)
                return
            _proxy_get(self, headers, f"{PP}/test-assignments/{aid}", {})
            return

        if not sid:
            send_json(self, {"error": "Missing student param", "testAssignments": []}, 400)
            return
        _proxy_get(self, headers, f"{PP}/test-assignments", {"student": sid})

    def do_DELETE(self):
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            body = json.loads(raw) if raw else {}
            aid = (body.get("assignmentId") or body.get("sourcedId") or "").strip()
            if not aid:
                send_json(self, {"success": False, "error": "assignmentId required"}, 400)
                return
            headers = api_headers()
            resp = requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=10)
            send_json(self, {"success": resp.status_code in (200, 204), "status": resp.status_code})
        except Exception as e:
            send_json(self, {"success": False, "error": str(e)}, 500)

    def do_POST(self):
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            if not raw:
                send_json(self, {"error": "Empty body", "success": False}, 400)
                return

            body = json.loads(raw)
            action = (body.get("action") or "").strip()

            # ── Reset placement ──
            if action == "resetPlacement":
                sid = (body.get("student") or body.get("studentId") or "").strip()
                subject = (body.get("subject") or "").strip()
                if not sid or not subject:
                    send_json(self, {"error": "Need student and subject", "success": False}, 400)
                    return
                headers = api_headers()
                resp = requests.post(
                    f"{PP}/placement/resetUserPlacement", headers=headers,
                    json={"student": sid, "subject": subject}, timeout=10,
                )
                try:
                    rdata = resp.json()
                except Exception:
                    rdata = {"status": resp.status_code}
                send_json(self, {"success": resp.status_code in (200, 201, 204), "response": rdata}, resp.status_code if resp.status_code >= 400 else 200)
                return

            # ── Assign test ──
            sid = (body.get("student") or body.get("studentId") or "").strip()
            subject = (body.get("subject") or "").strip()
            grade = (body.get("grade") or body.get("gradeLevel") or "").strip()

            if not sid:
                send_json(self, {"error": "student is required", "success": False}, 400)
                return
            if not subject or not grade:
                send_json(self, {"error": "subject and grade are required", "success": False}, 400)
                return

            headers = api_headers()

            # Delete any existing assignments for this subject first
            try:
                lr = requests.get(f"{PP}/test-assignments", headers=headers, params={"student": sid}, timeout=8)
                if lr.status_code == 200:
                    for a in lr.json().get("testAssignments", []):
                        if (a.get("subject") or "").lower() == subject.lower():
                            aid = a.get("sourcedId") or a.get("assignmentId") or ""
                            if aid:
                                requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=6)
            except Exception:
                pass

            # Assign the test
            payload = {"student": sid, "subject": subject, "grade": grade}
            resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=12)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}

            if resp.status_code in (200, 201):
                send_json(self, {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "response": data,
                })
            else:
                err = ""
                if isinstance(data, dict):
                    err = data.get("error") or data.get("imsx_description") or data.get("message") or ""

                # Clear error message for the admin
                if "not enrolled" in (err or "").lower():
                    friendly = f"Cannot assign {subject} Grade {grade} — this course is not set up in PowerPath for this student. Enroll the student in {subject} Grade {grade} first."
                elif resp.status_code == 500:
                    friendly = f"{subject} Grade {grade} test is not available in PowerPath. This grade level may not have test content configured."
                else:
                    friendly = err or f"PowerPath returned {resp.status_code}"

                send_json(self, {
                    "success": False,
                    "error": friendly,
                    "httpStatus": resp.status_code,
                }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _proxy_get(handler, headers, url, params):
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            send_json(handler, resp.json())
        else:
            try:
                send_json(handler, resp.json(), resp.status_code)
            except Exception:
                send_json(handler, {"error": f"HTTP {resp.status_code}"}, resp.status_code)
    except Exception as e:
        send_json(handler, {"error": str(e)}, 500)
