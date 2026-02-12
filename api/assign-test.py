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

            # Step 5: Create OneRoster assessment result (this is what MasteryTrack reads)
            assignment_id = str(uuid.uuid4())
            if isinstance(pp_data, dict) and pp_data.get("assignmentId"):
                assignment_id = pp_data["assignmentId"]

            test_name = f"{subject} Grade {grade} Test"
            ar_result = _create_mastery_track_assignment(
                headers, assignment_id, sid, email, subject, grade, test_name
            )
            log["masteryTrack"] = ar_result

            # Return success if either PowerPath or MasteryTrack assignment succeeded
            pp_ok = pp_resp.status_code in (200, 201)
            mt_ok = ar_result.get("success", False)

            if pp_ok or mt_ok:
                msg = f"Test assigned ({subject} Grade {grade})"
                if pp_ok:
                    msg += " — available in MasteryTrack"
                else:
                    msg += " — record created (PowerPath unavailable for this grade)"
                send_json(self, {
                    "success": True,
                    "message": msg,
                    "response": pp_data if pp_ok else ar_result,
                    "assignmentId": assignment_id,
                    "testLink": "https://alphatest.alpha.school",
                    "powerpathOk": pp_ok,
                    "log": log,
                })
            else:
                err = ""
                if isinstance(pp_data, dict):
                    err = pp_data.get("error") or pp_data.get("imsx_description") or ""
                send_json(self, {
                    "success": False,
                    "error": err or f"Assignment failed",
                    "log": log,
                }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _create_mastery_track_assignment(headers, assignment_id, student_id, email, subject, grade, test_name):
    """Create an assessment result in OneRoster gradebook so MasteryTrack can see it."""
    ar = {
        "assessmentResult": {
            "sourcedId": assignment_id,
            "status": "active",
            "metadata": {
                "xp": 0,
                "subject": subject,
                "grade": grade,
                "testName": test_name,
                "testType": "assessment",
                "toolProvider": "AlphaTest",
                "studentEmail": email,
            },
            "assessmentLineItem": {"sourcedId": ALPHATEST_LINE_ITEM},
            "student": {"sourcedId": student_id},
            "score": 0,
            "scoreDate": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "scoreStatus": "not submitted",
            "inProgress": "false",
            "incomplete": "false",
            "late": "false",
            "missing": "false",
        }
    }

    try:
        resp = requests.put(
            f"{OR}/gradebook/v1p2/assessmentResults/{assignment_id}",
            headers=headers,
            json=ar,
            timeout=10,
        )
        try:
            body = resp.json()
        except Exception:
            body = {}
        return {"success": resp.status_code in (200, 201), "status": resp.status_code, "response": body}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
