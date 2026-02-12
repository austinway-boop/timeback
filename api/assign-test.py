"""POST /api/assign-test — Assign a test via PowerPath.
GET  /api/assign-test?student=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.
GET  /api/assign-test?action=placement&student=...&subject=... — Get placement level.

PowerPath API (docs.timeback.com):
  POST /powerpath/test-assignments  { student, subject, grade }  → { assignmentId, lessonId, resourceId }
  GET  /powerpath/test-assignments  ?student=sourcedId            → { testAssignments: [...] }
  DEL  /powerpath/test-assignments/{id}
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

        if action == "placement":
            subject = params.get("subject", [""])[0].strip()
            if not subject:
                send_json(self, {"error": "Missing subject param"}, 400)
                return
            try:
                resp = requests.get(f"{PP}/placement/getCurrentLevel", headers=headers, params={"student": sid, "subject": subject}, timeout=10)
                send_json(self, resp.json() if resp.status_code == 200 else {"error": f"Status {resp.status_code}"})
            except Exception as e:
                send_json(self, {"error": str(e)})
            return

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
                    r = requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=10)
                    if r.status_code in (200, 204):
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

            # ── Create test assignment ────────────────────────────
            # Docs: POST /powerpath/test-assignments { student, subject, grade }
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
                return

            # ── Failed — return full diagnostic info ──────────────
            err = ""
            if isinstance(data, dict):
                err = data.get("imsx_description") or data.get("error") or data.get("message") or ""

            # Check placement to give a useful hint
            hint = ""
            try:
                pl = requests.get(f"{PP}/placement/getCurrentLevel", headers=headers, params={"student": sid, "subject": subject}, timeout=6)
                if pl.status_code == 200:
                    pld = pl.json()
                    plg = pld.get("gradeLevel") or pld.get("grade")
                    if isinstance(plg, dict):
                        plg = plg.get("level") or plg.get("grade")
                    if plg is not None:
                        hint = f" (Placement: Grade {plg} in {subject})"
            except Exception:
                pass

            send_json(self, {
                "success": False,
                "error": (err or f"PowerPath returned {resp.status_code}") + hint,
                "httpStatus": resp.status_code,
                "powerpathResponse": data,
                "sentPayload": payload,
                "apiUrl": f"{PP}/test-assignments",
            }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
