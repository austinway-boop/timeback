"""PowerPath test assignment + placement API proxy.

Confirmed endpoints (all on API_BASE = https://api.alpha-1edtech.ai):

  POST /powerpath/test-assignments                              — Assign test
  GET  /powerpath/test-assignments?student={id}                 — Student assignments
  GET  /powerpath/test-assignments/admin                        — All assignments (admin)
  GET  /powerpath/test-assignments/{id}                         — Single assignment
  DEL  /powerpath/test-assignments/{id}                         — Delete assignment
  GET  /powerpath/placement/subjects                            — All placement subjects
  GET  /powerpath/placement/getCurrentLevel?student={id}&subject={s}  — Current level
  GET  /powerpath/placement/getSubjectProgress?student={id}&subject={s} — Progress

Frontend routes this via query params:
  GET  /api/assign-test?student={id}                    → list student assignments
  GET  /api/assign-test?action=admin                    → list all assignments
  GET  /api/assign-test?action=placement&student={id}&subject={s}  → current level
  GET  /api/assign-test?action=progress&student={id}&subject={s}   → subject progress
  GET  /api/assign-test?action=subjects                 → placement subjects
  GET  /api/assign-test?action=get&id={assignmentId}    → single assignment
  POST /api/assign-test  { student, subject, grade }    → assign test
  DEL  /api/assign-test  { assignmentId }               → delete assignment
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

        # ── Placement: current level ──
        if action == "placement":
            if not sid or not subject:
                send_json(self, {"error": "Need student and subject params"}, 400)
                return
            _proxy_get(self, headers, f"{PP}/placement/getCurrentLevel", {"student": sid, "subject": subject})
            return

        # ── Placement: subject progress ──
        if action == "progress":
            if not sid or not subject:
                send_json(self, {"error": "Need student and subject params"}, 400)
                return
            _proxy_get(self, headers, f"{PP}/placement/getSubjectProgress", {"student": sid, "subject": subject})
            return

        # ── Placement: all subjects ──
        if action == "subjects":
            _proxy_get(self, headers, f"{PP}/placement/subjects", {})
            return

        # ── Admin: all assignments ──
        if action == "admin":
            _proxy_get(self, headers, f"{PP}/test-assignments/admin", {})
            return

        # ── Single assignment by ID ──
        if action == "get":
            aid = params.get("id", [""])[0].strip()
            if not aid:
                send_json(self, {"error": "Need id param"}, 400)
                return
            _proxy_get(self, headers, f"{PP}/test-assignments/{aid}", {})
            return

        # ── Student assignments (default) ──
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
            payload = {"student": sid, "subject": subject, "grade": grade}

            resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=12)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}

            if resp.status_code in (200, 201):
                # Step 2: Provision on MasteryTrack via screening.assignTest
                # Uses the resourceId from the assignment as the testId
                mt_result = None
                if isinstance(data, dict):
                    resource_id = data.get("resourceId") or data.get("lessonId") or ""
                    assignment_id = data.get("assignmentId") or ""
                    if resource_id:
                        mt_result = _provision_mastery_track(headers, sid, resource_id, assignment_id)

                result = {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "response": data,
                }
                if mt_result:
                    result["masteryTrack"] = mt_result
                send_json(self, result)
            else:
                err = ""
                if isinstance(data, dict):
                    err = data.get("imsx_description") or data.get("error") or data.get("message") or ""
                send_json(self, {
                    "success": False,
                    "error": err or f"PowerPath returned {resp.status_code}",
                    "httpStatus": resp.status_code,
                    "powerpathResponse": data,
                }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _provision_mastery_track(headers, student_id, resource_id, assignment_id):
    """Provision the test on MasteryTrack via screening.assignTest.
    SDK: client.screening.assignTest({ studentId, testId })
    This makes the test available at alphatest.alpha.school/assignment/{assignmentId}
    """
    # Try with resourceId first, then assignmentId as testId
    test_ids = [resource_id, assignment_id] if resource_id != assignment_id else [resource_id]

    for test_id in test_ids:
        if not test_id:
            continue
        # Try multiple endpoint path patterns
        for path in [
            f"{PP}/screening/assignTest",
            f"{PP}/screening/tests/assign",
        ]:
            try:
                resp = requests.post(
                    path, headers=headers,
                    json={"studentId": student_id, "testId": test_id},
                    timeout=8,
                )
                if resp.status_code in (200, 201):
                    try:
                        return resp.json()
                    except Exception:
                        return {"status": "provisioned"}
                elif resp.status_code == 404:
                    continue  # try next path
                else:
                    # Got a real response — return it for debugging
                    try:
                        return {"status": resp.status_code, "response": resp.json()}
                    except Exception:
                        return {"status": resp.status_code}
            except Exception:
                continue
    return None


def _proxy_get(handler, headers, url, params):
    """Simple GET proxy — forward to PowerPath and return the response."""
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
