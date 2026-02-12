"""MasteryTrack test assignment API.

Flow:
  1. Enroll student in placement class (OneRoster enrollment)
  2. Assign test (PowerPath test-assignments)
  3. Student takes test at alphatest.alpha.school/assignment/{assignmentId}

Placement Class IDs:
  Math     → 514efb44-d13b-41bd-8d6a-dc380b2e5ca2 (school: cf49acb1...)
  Language → 0b7b2884-cf93-4a09-b1ac-6ebfe9f96f39 (school: f47ac10b...)
  Science  → science-placement-tests-class-timeback (school: cf49acb1...)
  Writing  → writing-placement-tests-class-timeback (school: cf49acb1...)
"""

import json
import time
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json

PP = f"{API_BASE}/powerpath"
OR = f"{API_BASE}/ims/oneroster/rostering/v1p2"

# Placement class IDs — required for enrollment before test assignment
PLACEMENT_CLASSES = {
    "math":     {"classId": "514efb44-d13b-41bd-8d6a-dc380b2e5ca2", "schoolId": "cf49acb1-1e67-48c6-8d53-8b3c6a404852"},
    "language":  {"classId": "0b7b2884-cf93-4a09-b1ac-6ebfe9f96f39", "schoolId": "f47ac10b-58cc-4372-a567-0e02b2c3d479"},
    "science":  {"classId": "science-placement-tests-class-timeback", "schoolId": "cf49acb1-1e67-48c6-8d53-8b3c6a404852"},
    "writing":  {"classId": "writing-placement-tests-class-timeback", "schoolId": "cf49acb1-1e67-48c6-8d53-8b3c6a404852"},
}
# Aliases
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
        sid = (params.get("student", params.get("studentId", [""]))  [0]).strip()
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

            if not sid or not subject or not grade:
                send_json(self, {"error": "Need student, subject, and grade", "success": False}, 400)
                return

            headers = api_headers()

            # Step 1: Delete any existing assignments for this subject
            try:
                lr = requests.get(f"{PP}/test-assignments", headers=headers, params={"student": sid}, timeout=8)
                if lr.status_code == 200:
                    for a in lr.json().get("testAssignments", []):
                        if (a.get("subject") or "").lower() == subject.lower():
                            aid = a.get("sourcedId") or ""
                            if aid:
                                requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=6)
            except Exception:
                pass

            # Step 2: Reset placement for this subject
            try:
                requests.post(f"{PP}/placement/resetUserPlacement", headers=headers, json={"student": sid, "subject": subject}, timeout=6)
            except Exception:
                pass

            # Step 3: Ensure enrollment in placement class (OneRoster)
            enroll_result = _ensure_placement_enrollment(headers, sid, subject)

            # Step 4: Assign the test
            payload = {"student": sid, "subject": subject, "grade": grade}
            resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=12)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}

            if resp.status_code in (200, 201):
                aid = data.get("assignmentId", "") if isinstance(data, dict) else ""
                lid = data.get("lessonId", "") if isinstance(data, dict) else ""
                send_json(self, {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "response": data,
                    "testLink": f"https://alpha.timeback.com/app/lesson/{lid}" if lid else "",
                    "altLinks": {
                        "timeback": f"https://alpha.timeback.com/app/lesson/{lid}" if lid else "",
                        "mastery": f"https://alphatest.alpha.school/assignment/{aid}" if aid else "",
                    },
                })
                return

            # Failed — return error
            err = ""
            if isinstance(data, dict):
                err = data.get("error") or data.get("imsx_description") or ""
            send_json(self, {
                "success": False,
                "error": err or f"PowerPath returned {resp.status_code}",
                "httpStatus": resp.status_code,
                "enrollment": enroll_result,
                "powerpathResponse": data,
            }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _ensure_placement_enrollment(headers, student_id, subject):
    """Enroll student in the placement class via OneRoster (required before test assignment)."""
    key = subject.lower()
    cls = PLACEMENT_CLASSES.get(key)
    if not cls:
        return {"enrolled": False, "reason": f"No placement class for '{subject}'"}

    class_id = cls["classId"]
    school_id = cls["schoolId"]
    enrollment_id = f"enrollment-{student_id}-{key}-{int(time.time())}"

    enrollment = {
        "enrollment": {
            "sourcedId": enrollment_id,
            "status": "active",
            "role": "student",
            "primary": "false",
            "user": {"sourcedId": student_id},
            "class": {"sourcedId": class_id},
            "school": {"sourcedId": school_id},
        }
    }

    try:
        resp = requests.post(
            f"{OR}/enrollments",
            headers=headers,
            json=enrollment,
            timeout=10,
        )
        # 200/201 = created, 422/409 = already exists (both are fine)
        ok = resp.status_code in (200, 201, 422, 409)
        return {"enrolled": ok, "status": resp.status_code, "classId": class_id}
    except Exception as e:
        return {"enrolled": False, "error": str(e)}


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
