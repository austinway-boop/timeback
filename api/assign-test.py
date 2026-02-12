"""MasteryTrack test assignment API — v3 (lineItems via rostering POST).

Assignment flow:
  1. DELETE old assignments for subject
  2. Reset placement
  3. Ensure enrollment in placement class
  4. POST /powerpath/test-assignments (PowerPath record)
  5. POST /ims/oneroster/rostering/v1p2/lineItems (syncs to MasteryTrack)
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
            deleted = []

            # 1. Delete from PowerPath
            try:
                r = requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=10)
                deleted.append({"target": "powerpath", "status": r.status_code})
            except Exception:
                pass

            # 2. Delete OneRoster assessment result (same sourcedId)
            try:
                r = requests.delete(f"{OR}/gradebook/v1p2/assessmentResults/{aid}", headers=headers, timeout=6)
                deleted.append({"target": "assessmentResult", "status": r.status_code})
            except Exception:
                pass

            # 3. Soft-delete by updating status to "tobedeleted"
            try:
                r = requests.put(
                    f"{OR}/gradebook/v1p2/assessmentResults/{aid}",
                    headers=headers,
                    json={"assessmentResult": {"sourcedId": aid, "status": "tobedeleted"}},
                    timeout=6,
                )
                deleted.append({"target": "softDelete", "status": r.status_code})
            except Exception:
                pass

            # 4. Delete OneRoster line item (same sourcedId)
            try:
                r = requests.delete(f"{OR}/gradebook/v1p2/lineItems/{aid}", headers=headers, timeout=6)
                deleted.append({"target": "lineItem", "status": r.status_code})
            except Exception:
                pass

            send_json(self, {"success": True, "deleted": deleted})
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

            pp_ok = pp_resp.status_code in (200, 201)

            assignment_id = ""
            lesson_id = ""
            if isinstance(pp_data, dict):
                assignment_id = pp_data.get("assignmentId") or ""
                lesson_id = pp_data.get("lessonId") or ""

            # Step 5: Provision on MasteryTrack via Timeback's makeExternalTestAssignment
            mt_result = None
            test_link = ""
            if pp_ok and (lesson_id or assignment_id):
                mt_result = _make_external_test_assignment(sid, lesson_id or assignment_id)
                log["masteryTrack"] = mt_result
                if mt_result and mt_result.get("success"):
                    test_link = mt_result.get("testUrl") or ""

            if not test_link and assignment_id:
                test_link = f"https://alphatest.alpha.school/assignment/{assignment_id}"

            if pp_ok:
                send_json(self, {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "assignmentId": assignment_id,
                    "testLink": test_link,
                    "response": pp_data,
                    "log": log,
                })
            else:
                # PowerPath failed — try line item as fallback
                test_name = f"{subject} Grade {grade} Test"
                fallback_id = assignment_id or str(uuid.uuid4())
                li_result = _create_line_item(headers, fallback_id, sid, email, subject, grade, test_name)
                log["lineItem"] = li_result

                if li_result.get("success"):
                    send_json(self, {
                        "success": True,
                        "message": f"Test assigned ({subject} Grade {grade})",
                        "assignmentId": fallback_id,
                        "testLink": f"https://alphatest.alpha.school/assignment/{fallback_id}",
                        "response": li_result,
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


def _make_external_test_assignment(student_id, lesson_id):
    """Call Timeback's makeExternalTestAssignment server function.
    This provisions the test on MasteryTrack and returns the numeric test ID + URL."""
    url = "https://alpha.timeback.com/_serverFn/src_features_powerpath-quiz_services_lesson-mastery_ts--makeExternalTestAssignment_createServerFn_handler"
    try:
        resp = requests.post(
            url,
            params={"createServerFn": ""},
            headers={"Content-Type": "application/json"},
            json={"data": {"student": student_id, "lesson": lesson_id}, "context": {}},
            timeout=10,
        )
        try:
            body = resp.json()
        except Exception:
            return {"success": False, "status": resp.status_code, "raw": resp.text[:300]}

        result = body.get("result", {})
        if result.get("success"):
            return {
                "success": True,
                "testId": result.get("testId"),
                "testUrl": result.get("testUrl"),
                "assignmentId": result.get("assignmentId"),
                "credentials": result.get("credentials"),
            }
        return {"success": False, "status": resp.status_code, "response": body}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _create_line_item(headers, assignment_id, student_id, email, subject, grade, test_name):
    """Create a OneRoster line item that syncs to MasteryTrack.
    Fetches real class, school, and category IDs from OneRoster first."""

    GB = f"{API_BASE}/ims/oneroster/gradebook/v1p2"
    RS = f"{API_BASE}/ims/oneroster/rostering/v1p2"
    log = {}

    # 1. Find the student's class for this subject (from their enrollments)
    class_id = ""
    school_id = ""
    try:
        er = requests.get(f"{RS}/students/{student_id}/classes", headers=headers, timeout=8)
        if er.status_code == 200:
            classes = er.json().get("classes", [])
            for c in classes:
                # Match by subject in course or title
                c_title = (c.get("title") or "").lower()
                c_subjects = c.get("subjects") or []
                c_grades = c.get("grades") or []
                subj_match = subject.lower() in c_title or subject.lower() in [s.lower() for s in c_subjects]
                if subj_match:
                    class_id = c.get("sourcedId") or ""
                    school_ref = c.get("school") or {}
                    school_id = school_ref.get("sourcedId") or ""
                    break
            # Fallback: use first class if no subject match
            if not class_id and classes:
                class_id = classes[0].get("sourcedId") or ""
                school_ref = classes[0].get("school") or {}
                school_id = school_ref.get("sourcedId") or ""
        log["classLookup"] = {"found": bool(class_id), "classId": class_id, "schoolId": school_id}
    except Exception as e:
        log["classLookup"] = {"error": str(e)}

    # Fallback to placement class IDs if no class found
    if not class_id:
        key = subject.lower()
        cls = PLACEMENT_CLASSES.get(key, PLACEMENT_CLASSES.get("math"))
        class_id = cls["classId"]
        school_id = cls["schoolId"]
        log["classLookup"] = {"fallback": True, "classId": class_id}

    # 2. Find a real category ID from the gradebook
    category_id = ""
    try:
        cr = requests.get(f"{GB}/categories", headers=headers, params={"limit": 10}, timeout=6)
        if cr.status_code == 200:
            cats = cr.json().get("categories", [])
            if cats:
                category_id = cats[0].get("sourcedId") or ""
        log["categoryLookup"] = {"found": bool(category_id), "id": category_id}
    except Exception as e:
        log["categoryLookup"] = {"error": str(e)}

    if not category_id:
        category_id = ALPHATEST_LINE_ITEM  # fallback

    # 3. Build the line item with real IDs and full ISO-8601 dates
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    inner = {
        "sourcedId": assignment_id,
        "status": "active",
        "title": test_name,
        "description": f"{subject} Grade {grade} placement test",
        "assignDate": now,
        "dueDate": "2026-12-31T23:59:59.000Z",
        "class": {"sourcedId": class_id},
        "school": {"sourcedId": school_id},
        "category": {"sourcedId": category_id},
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

    # 4. Try creating the line item
    attempts = []
    combos = [
        ("PUT",  f"{GB}/lineItems/{assignment_id}",               {"lineItem": inner}),
        ("POST", f"{GB}/lineItems",                                {"lineItem": inner}),
        ("PUT",  f"{GB}/assessmentLineItems/{assignment_id}",     {"assessmentLineItem": inner}),
        ("POST", f"{GB}/assessmentLineItems",                      {"assessmentLineItem": inner}),
    ]

    for method, url, payload in combos:
        try:
            if method == "PUT":
                resp = requests.put(url, headers=headers, json=payload, timeout=8)
            else:
                resp = requests.post(url, headers=headers, json=payload, timeout=8)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:300]}
            attempts.append({"method": method, "path": url.replace(API_BASE, ""), "status": resp.status_code})
            if resp.status_code in (200, 201):
                return {"success": True, "status": resp.status_code, "response": body, "attempts": attempts, **log}
        except Exception as e:
            attempts.append({"path": url.replace(API_BASE, ""), "error": str(e)})

    return {"success": False, "attempts": attempts, **log}


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
