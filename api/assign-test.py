"""MasteryTrack test assignment API.

Two-step assignment:
  1. POST /powerpath/test-assignments { student, subject, grade }  → PowerPath record
  2. PUT  /ims/oneroster/gradebook/v1p2/assessmentResults/{id}     → MasteryTrack sees it

MasteryTrack reads from OneRoster gradebook (assessmentResults with toolProvider: "AlphaTest").
PowerPath alone does NOT make tests appear in MasteryTrack.
"""

import json
import time
import uuid
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json

PP = f"{API_BASE}/powerpath"
OR = f"{API_BASE}/ims/oneroster"

# Assessment line item used by AlphaTest/MasteryTrack
ALPHATEST_LINE_ITEM = "a003e5f6-8ea0-4949-a82c-3ac0cd1e23ff"

# Placement class IDs for OneRoster enrollment
PLACEMENT_CLASSES = {
    "math":     {"classId": "514efb44-d13b-41bd-8d6a-dc380b2e5ca2", "schoolId": "cf49acb1-1e67-48c6-8d53-8b3c6a404852"},
    "language":  {"classId": "0b7b2884-cf93-4a09-b1ac-6ebfe9f96f39", "schoolId": "f47ac10b-58cc-4372-a567-0e02b2c3d479"},
    "science":  {"classId": "science-placement-tests-class-timeback", "schoolId": "cf49acb1-1e67-48c6-8d53-8b3c6a404852"},
    "writing":  {"classId": "writing-placement-tests-class-timeback", "schoolId": "cf49acb1-1e67-48c6-8d53-8b3c6a404852"},
}
PLACEMENT_CLASSES["reading"] = PLACEMENT_CLASSES["language"]
PLACEMENT_CLASSES["vocabulary"] = PLACEMENT_CLASSES["language"]
PLACEMENT_CLASSES["social studies"] = PLACEMENT_CLASSES["science"]
PLACEMENT_CLASSES["fastmath"] = PLACEMENT_CLASSES["math"]


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
        sid = (params.get("student", params.get("studentId", [""]))[0]).strip()
        subject = params.get("subject", [""])[0].strip()
        headers = api_headers()

        if action == "placement":
            if not sid or not subject:
                send_json(self, {"error": "Need student and subject"}, 400)
                return
            _proxy_get(self, headers, f"{PP}/placement/getCurrentLevel", {"student": sid, "subject": subject})
            return
        if action == "progress":
            if not sid or not subject:
                send_json(self, {"error": "Need student and subject"}, 400)
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
                send_json(self, {"error": "Need id"}, 400)
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
            # Delete from PowerPath
            resp = requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=10)
            # Also try to delete the OneRoster assessment result
            try:
                requests.delete(f"{OR}/gradebook/v1p2/assessmentResults/{aid}", headers=headers, timeout=6)
            except Exception:
                pass
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

            if action == "resetPlacement":
                sid = (body.get("student") or body.get("studentId") or "").strip()
                subject = (body.get("subject") or "").strip()
                if not sid or not subject:
                    send_json(self, {"error": "Need student and subject", "success": False}, 400)
                    return
                headers = api_headers()
                resp = requests.post(f"{PP}/placement/resetUserPlacement", headers=headers, json={"student": sid, "subject": subject}, timeout=10)
                try:
                    d = resp.json()
                except Exception:
                    d = {}
                send_json(self, {"success": resp.status_code in (200, 201, 204), "response": d})
                return

            # ── Assign test ──
            sid = (body.get("student") or body.get("studentId") or "").strip()
            subject = (body.get("subject") or "").strip()
            grade = (body.get("grade") or body.get("gradeLevel") or "").strip()
            email = (body.get("email") or "").strip()

            if not sid or not subject or not grade:
                send_json(self, {"error": "Need student, subject, and grade", "success": False}, 400)
                return

            headers = api_headers()
            log = {}

            # Look up student email if not provided (MasteryTrack needs it)
            if not email:
                try:
                    ur = requests.get(f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{sid}", headers=headers, timeout=6)
                    if ur.status_code == 200:
                        ud = ur.json()
                        user = ud.get("user", ud)
                        email = user.get("email", "")
                except Exception:
                    pass

            # Step 1: Delete old assignments for this subject
            try:
                lr = requests.get(f"{PP}/test-assignments", headers=headers, params={"student": sid}, timeout=8)
                if lr.status_code == 200:
                    for a in lr.json().get("testAssignments", []):
                        if (a.get("subject") or "").lower() == subject.lower():
                            old_id = a.get("sourcedId") or ""
                            if old_id:
                                requests.delete(f"{PP}/test-assignments/{old_id}", headers=headers, timeout=6)
                                try:
                                    requests.delete(f"{OR}/gradebook/v1p2/assessmentResults/{old_id}", headers=headers, timeout=6)
                                except Exception:
                                    pass
            except Exception:
                pass

            # Step 2: Reset placement
            try:
                requests.post(f"{PP}/placement/resetUserPlacement", headers=headers, json={"student": sid, "subject": subject}, timeout=6)
            except Exception:
                pass

            # Step 3: Ensure enrollment in placement class
            _ensure_placement_enrollment(headers, sid, subject)

            # Step 4: Create PowerPath assignment
            payload = {"student": sid, "subject": subject, "grade": grade}
            pp_resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=12)
            try:
                pp_data = pp_resp.json()
            except Exception:
                pp_data = {}
            log["powerpath"] = {"status": pp_resp.status_code}

            assignment_id = str(uuid.uuid4())
            if isinstance(pp_data, dict) and pp_data.get("assignmentId"):
                assignment_id = pp_data["assignmentId"]

            # Step 5: Create OneRoster line item (syncs to MasteryTrack)
            test_name = f"{subject} Grade {grade} Test"
            li_result = _create_line_item(headers, assignment_id, sid, email, subject, grade, test_name)
            log["lineItem"] = li_result

            pp_ok = pp_resp.status_code in (200, 201)
            li_ok = li_result.get("success", False)

            if pp_ok or li_ok:
                send_json(self, {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "assignmentId": assignment_id,
                    "testLink": "https://alphatest.alpha.school",
                    "response": pp_data if pp_ok else li_result,
                    "log": log,
                })
            else:
                err = ""
                if isinstance(pp_data, dict):
                    err = pp_data.get("error") or pp_data.get("imsx_description") or ""
                send_json(self, {
                    "success": False,
                    "error": err or "Assignment failed",
                    "log": log,
                }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _create_line_item(headers, assignment_id, student_id, email, subject, grade, test_name):
    """Create a OneRoster line item that syncs to MasteryTrack's assignment system."""
    # Get the placement class for this subject (used as the class reference)
    key = subject.lower()
    cls = PLACEMENT_CLASSES.get(key, PLACEMENT_CLASSES.get("math"))
    class_id = cls["classId"]

    line_item = {
        "lineItem": {
            "sourcedId": assignment_id,
            "status": "active",
            "title": test_name,
            "description": f"{subject} Grade {grade} placement test for {email}",
            "assignDate": time.strftime("%Y-%m-%d", time.gmtime()),
            "dueDate": "2026-12-31",
            "class": {"sourcedId": class_id},
            "category": {"sourcedId": ALPHATEST_LINE_ITEM},
            "resultValueMin": 0.0,
            "resultValueMax": 100.0,
            "metadata": {
                "toolProvider": "AlphaTest",
                "subject": subject,
                "grade": grade,
                "testType": "assessment",
                "studentSourcedId": student_id,
                "studentEmail": email,
            },
        }
    }

    results = {}

    # Try multiple paths — gradebook and rostering
    for path in [
        f"{OR}/gradebook/v1p2/lineItems/{assignment_id}",
        f"{OR}/rostering/v1p2/lineItems/{assignment_id}",
    ]:
        try:
            resp = requests.put(path, headers=headers, json=line_item, timeout=10)
            try:
                body = resp.json()
            except Exception:
                body = {"status": resp.status_code}
            results[path.split("/v1p2/")[0].split("/")[-1]] = {"status": resp.status_code}
            if resp.status_code in (200, 201):
                return {"success": True, "status": resp.status_code, "response": body, "attempts": results}
        except Exception as e:
            results["error"] = str(e)

    return {"success": False, "attempts": results}


def _ensure_placement_enrollment(headers, student_id, subject):
    """Enroll student in placement class via OneRoster."""
    key = subject.lower()
    cls = PLACEMENT_CLASSES.get(key)
    if not cls:
        return
    try:
        enrollment = {
            "enrollment": {
                "sourcedId": f"enrollment-{student_id}-{key}-{int(time.time())}",
                "status": "active",
                "role": "student",
                "primary": "false",
                "user": {"sourcedId": student_id},
                "class": {"sourcedId": cls["classId"]},
                "school": {"sourcedId": cls["schoolId"]},
            }
        }
        requests.post(f"{OR}/rostering/v1p2/enrollments", headers=headers, json=enrollment, timeout=8)
    except Exception:
        pass


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
