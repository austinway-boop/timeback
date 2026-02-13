"""Test assignment API — creates test-out assignments on MasteryTrack.

Flow:
  1. POST /powerpath/test-assignments { student, subject, grade }
     → Creates unlisted test-out → { assignmentId, lessonId, resourceId }
  2. Frontend calls makeExternalTestAssignment with lessonId
     → Provisions on MasteryTrack → { testId, testUrl }
"""

import json
import time
import uuid
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json

PP = f"{API_BASE}/powerpath"
OR = f"{API_BASE}/ims/oneroster"

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
            _proxy(self, headers, f"{PP}/placement/getCurrentLevel", {"student": sid, "subject": subject})
            return
        if action == "progress":
            _proxy(self, headers, f"{PP}/placement/getSubjectProgress", {"student": sid, "subject": subject})
            return
        if action == "subjects":
            _proxy(self, headers, f"{PP}/placement/subjects", {})
            return
        if action == "admin":
            _proxy(self, headers, f"{PP}/test-assignments/admin", {})
            return
        if action == "get":
            _proxy(self, headers, f"{PP}/test-assignments/{params.get('id', [''])[0]}", {})
            return
        if not sid:
            send_json(self, {"error": "Missing student", "testAssignments": []}, 400)
            return
        _proxy(self, headers, f"{PP}/test-assignments", {"student": sid})

    def do_DELETE(self):
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            body = json.loads(raw) if raw else {}
            aid = (body.get("assignmentId") or body.get("sourcedId") or "").strip()
            sid = (body.get("student") or body.get("studentId") or "").strip()
            subject = (body.get("subject") or "").strip()
            if not aid:
                send_json(self, {"success": False, "error": "assignmentId required"}, 400)
                return
            headers = api_headers()
            r = requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=10)
            deleted = r.status_code in (200, 204)

            # After removing the test, clean up the placement enrollment
            # if no other tests remain for this subject
            enrollment_removed = False
            if deleted and sid and subject:
                try:
                    enrollment_removed = _cleanup_placement_enrollment(headers, sid, subject)
                except Exception:
                    pass

            send_json(self, {
                "success": deleted,
                "status": r.status_code,
                "enrollmentRemoved": enrollment_removed,
            })
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

            if not sid or not subject or not grade:
                send_json(self, {"error": "Need student, subject, and grade", "success": False}, 400)
                return

            headers = api_headers()

            # Step 1: Delete any existing assignment for this subject
            try:
                lr = requests.get(f"{PP}/test-assignments", headers=headers, params={"student": sid}, timeout=8)
                if lr.status_code == 200:
                    for a in lr.json().get("testAssignments", []):
                        if (a.get("subject") or "").lower() == subject.lower():
                            old = a.get("sourcedId") or ""
                            if old:
                                requests.delete(f"{PP}/test-assignments/{old}", headers=headers, timeout=6)
            except Exception:
                pass

            # Step 2: Ensure enrollment in placement class
            _ensure_enrollment(headers, sid, subject)

            # Step 3: Create test-out assignment (NO placement reset — that makes it placement type)
            payload = {"student": sid, "subject": subject, "grade": grade}
            resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=12)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}

            if resp.status_code in (200, 201):
                lesson_id = data.get("lessonId", "") if isinstance(data, dict) else ""
                send_json(self, {
                    "success": True,
                    "message": f"Test-out assigned ({subject} Grade {grade})",
                    "response": data,
                    "assignmentId": data.get("assignmentId", ""),
                    "lessonId": lesson_id,
                })
            else:
                err = ""
                if isinstance(data, dict):
                    err = data.get("error") or data.get("imsx_description") or ""
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


def _ensure_enrollment(headers, student_id, subject):
    key = subject.lower()
    cls = PLACEMENT_CLASSES.get(key)
    if not cls:
        return
    try:
        requests.post(
            f"{OR}/rostering/v1p2/enrollments",
            headers=headers,
            json={"enrollment": {
                "sourcedId": f"enroll-{student_id}-{key}-{int(time.time())}",
                "status": "active", "role": "student", "primary": "false",
                "user": {"sourcedId": student_id},
                "class": {"sourcedId": cls["classId"]},
                "school": {"sourcedId": cls["schoolId"]},
            }},
            timeout=8,
        )
    except Exception:
        pass


def _cleanup_placement_enrollment(headers, student_id, subject):
    """Remove the placement-class enrollment if no other tests remain for this subject.

    Returns True if an enrollment was removed, False otherwise.
    """
    key = subject.lower()
    cls = PLACEMENT_CLASSES.get(key)
    if not cls:
        return False

    # Check if student still has other test assignments for this subject
    try:
        resp = requests.get(
            f"{PP}/test-assignments",
            headers=headers,
            params={"student": student_id},
            timeout=8,
        )
        if resp.status_code == 200:
            remaining = [
                a for a in resp.json().get("testAssignments", [])
                if (a.get("subject") or "").lower() == key
            ]
            if remaining:
                return False  # Other tests still exist — keep enrollment
    except Exception:
        pass  # If we can't check, still try to clean up

    # Find the placement enrollment to remove
    target_class_id = cls["classId"]
    try:
        resp = requests.get(
            f"{API_BASE}/edubridge/enrollments/user/{student_id}",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return False

        data = resp.json()
        enrollments = data.get("enrollments", data.get("data", []))

        for e in enrollments:
            course = e.get("course", {})
            course_id = course.get("id", "") if isinstance(course, dict) else ""
            enrollment_id = e.get("id", e.get("sourcedId", ""))

            if not enrollment_id:
                continue

            # Match by placement class ID or by course ID pattern
            if course_id == target_class_id:
                # Try to delete this enrollment
                dr = requests.delete(
                    f"{OR}/rostering/v1p2/enrollments/{enrollment_id}",
                    headers=headers,
                    timeout=10,
                )
                if dr.status_code in (200, 204):
                    return True
                # Fallback: try EduBridge delete
                dr = requests.delete(
                    f"{API_BASE}/edubridge/enrollments/{enrollment_id}",
                    headers=headers,
                    timeout=10,
                )
                if dr.status_code in (200, 204):
                    return True
    except Exception:
        pass

    return False


def _proxy(handler, headers, url, params):
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
