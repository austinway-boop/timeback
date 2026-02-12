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
            action = (body.get("action") or "").strip()

            # ── Reset placement action ──
            if action == "resetPlacement":
                sid = (body.get("student") or body.get("studentId") or "").strip()
                subject = (body.get("subject") or "").strip()
                if not sid or not subject:
                    send_json(self, {"error": "Need student and subject", "success": False}, 400)
                    return
                headers = api_headers()
                try:
                    resp = requests.post(
                        f"{PP}/placement/resetUserPlacement",
                        headers=headers,
                        json={"studentId": sid, "subject": subject},
                        timeout=10,
                    )
                    try:
                        rdata = resp.json()
                    except Exception:
                        rdata = {"status": resp.status_code}
                    if resp.status_code in (200, 201, 204):
                        send_json(self, {"success": True, "message": f"Placement reset for {subject}", "response": rdata})
                    else:
                        send_json(self, {"success": False, "error": f"HTTP {resp.status_code}", "response": rdata}, resp.status_code)
                except Exception as e:
                    send_json(self, {"success": False, "error": str(e)}, 500)
                return

            # ── Assign test action (default) ──
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
            log = {}

            # Full auto-fix flow: assign → if fail → enroll + reset + delete old → retry
            data, status = _assign_with_autofix(headers, sid, subject, grade, payload, log)

            if status in (200, 201):
                # Provision on MasteryTrack
                mt_result = None
                if isinstance(data, dict):
                    rid = data.get("resourceId") or data.get("lessonId") or ""
                    aid = data.get("assignmentId") or ""
                    if rid or aid:
                        mt_result = _provision_mastery_track(headers, sid, rid, aid)

                send_json(self, {
                    "success": True,
                    "message": f"Test assigned ({subject} Grade {grade})",
                    "response": data,
                    "masteryTrack": mt_result,
                })
            else:
                err = ""
                if isinstance(data, dict):
                    err = data.get("imsx_description") or data.get("error") or data.get("message") or ""
                send_json(self, {
                    "success": False,
                    "error": err or f"PowerPath returned {status}",
                    "httpStatus": status,
                    "powerpathResponse": data,
                    "log": log,
                }, 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _assign_with_autofix(headers, student_id, subject, grade, payload, log):
    """Try to assign. On failure: enroll in course + reset placement + delete old + retry.
    Returns (data_dict, http_status)."""

    # 1. First attempt
    resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=12)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}

    if resp.status_code in (200, 201):
        return data, resp.status_code

    log["firstAttempt"] = resp.status_code
    err = ""
    if isinstance(data, dict):
        err = (data.get("error") or data.get("imsx_description") or "").lower()

    # 2. If "not enrolled" error → find course and auto-enroll
    if "not enrolled" in err or resp.status_code == 400:
        log["autoEnroll"] = _auto_enroll(headers, student_id, subject, grade, log)

    # 3. Delete existing assignments for this subject
    try:
        lr = requests.get(f"{PP}/test-assignments", headers=headers, params={"student": student_id}, timeout=8)
        if lr.status_code == 200:
            deleted = []
            for a in lr.json().get("testAssignments", []):
                if (a.get("subject") or "").lower() == subject.lower():
                    aid = a.get("sourcedId") or a.get("assignmentId") or ""
                    if aid:
                        dr = requests.delete(f"{PP}/test-assignments/{aid}", headers=headers, timeout=6)
                        deleted.append({"id": aid, "status": dr.status_code})
            log["deleted"] = deleted
    except Exception:
        pass

    # 4. Reset placement (use "student" field — confirmed working)
    try:
        rr = requests.post(
            f"{PP}/placement/resetUserPlacement", headers=headers,
            json={"student": student_id, "subject": subject}, timeout=8,
        )
        try:
            log["placementReset"] = {"status": rr.status_code, "response": rr.json()}
        except Exception:
            log["placementReset"] = {"status": rr.status_code}
    except Exception as e:
        log["placementReset"] = {"error": str(e)}

    # 5. Retry assignment
    retry = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=12)
    try:
        retry_data = retry.json()
    except Exception:
        retry_data = {"raw": retry.text[:500]}
    log["retryStatus"] = retry.status_code

    if retry.status_code in (200, 201):
        return retry_data, retry.status_code
    return retry_data, retry.status_code


def _auto_enroll(headers, student_id, subject, grade, log):
    """Find the course for subject+grade and enroll the student via EduBridge."""
    EB = f"{API_BASE}/edubridge"

    # Search for matching course using subject tracks
    course_id = None
    try:
        # Try subject tracks first (maps subject+grade → courseId)
        st_resp = requests.get(f"{EB}/subject-tracks", headers=headers, timeout=8)
        if st_resp.status_code == 200:
            tracks = st_resp.json()
            if isinstance(tracks, list):
                for t in tracks:
                    if (t.get("subject") or "").lower() == subject.lower() and str(t.get("grade") or "") == str(grade):
                        course_id = t.get("courseId") or t.get("courseSourcedId") or ""
                        break
            elif isinstance(tracks, dict):
                for t in (tracks.get("data") or tracks.get("subjectTracks") or []):
                    if (t.get("subject") or "").lower() == subject.lower() and str(t.get("grade") or "") == str(grade):
                        course_id = t.get("courseId") or t.get("courseSourcedId") or ""
                        break
    except Exception:
        pass

    # Fallback: search courses by title pattern
    if not course_id:
        ordinal = {"1": "1st", "2": "2nd", "3": "3rd"}.get(grade, f"{grade}th")
        search_terms = [
            f"{subject} {ordinal} Grade",
            f"{subject} Grade {grade}",
            f"{subject} {grade}",
        ]
        try:
            cr = requests.get(
                f"{API_BASE}/ims/oneroster/rostering/v1p2/courses",
                headers=headers, params={"limit": 200}, timeout=10,
            )
            if cr.status_code == 200:
                courses = cr.json().get("courses", [])
                for term in search_terms:
                    for c in courses:
                        title = (c.get("title") or "").lower()
                        if term.lower() in title:
                            course_id = c.get("sourcedId") or ""
                            break
                    if course_id:
                        break
        except Exception:
            pass

    if not course_id:
        return {"enrolled": False, "reason": "Could not find course"}

    # Enroll the student
    try:
        enroll_resp = requests.post(
            f"{EB}/enrollments/enroll/{student_id}/{course_id}",
            headers=headers,
            json={"role": "student"},
            timeout=10,
        )
        try:
            enroll_data = enroll_resp.json()
        except Exception:
            enroll_data = {"status": enroll_resp.status_code}
        return {
            "enrolled": enroll_resp.status_code in (200, 201),
            "courseId": course_id,
            "status": enroll_resp.status_code,
            "response": enroll_data,
        }
    except Exception as e:
        return {"enrolled": False, "error": str(e)}


def _provision_mastery_track(headers, student_id, resource_id, assignment_id):
    """Provision the test on MasteryTrack via screening.assignTest.
    SDK: client.screening.assignTest({ studentId, testId })
    """
    # Try all IDs we have — resourceId, assignmentId, lessonId
    test_ids = list(dict.fromkeys([resource_id, assignment_id]))  # deduplicate, preserve order
    test_ids = [t for t in test_ids if t]

    attempts = []
    for test_id in test_ids:
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
                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text[:200]}

                attempts.append({
                    "path": path.split("/powerpath/")[-1],
                    "testId": test_id,
                    "status": resp.status_code,
                    "response": body,
                })

                if resp.status_code in (200, 201):
                    return {"provisioned": True, "details": body, "attempts": attempts}
                elif resp.status_code == 404:
                    continue
                else:
                    # Non-404 error — record and try next ID
                    break
            except Exception as e:
                attempts.append({"path": path, "testId": test_id, "error": str(e)})
                continue

    return {"provisioned": False, "attempts": attempts}


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
