"""POST /api/assign-test — Assign a test via PowerPath API + MasteryTrack.
GET  /api/assign-test?student=... — List test assignments for a student.
DELETE /api/assign-test — Remove a test assignment.
GET  /api/assign-test?action=placement&student=...&subject=... — Get placement level.

Full assignment flow (from PowerPath MasteryTrack docs):
  1. POST /powerpath/test-assignments { student, subject, grade }
     → creates assignment record → { assignmentId, lessonId, resourceId }
  2. POST /powerpath/lessonPlans/operations
     → { operations: [{ type: "makeExternalTestAssignment",
         toolProvider: "mastery-track", lessonId, studentId }] }
     → authenticates student on MasteryTrack, returns test link + credentials
  3. (Later) importExternalTestAssignmentResults to process scores after test ends
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

        # Placement check
        if action == "placement":
            subject = params.get("subject", [""])[0].strip()
            if not subject:
                send_json(self, {"error": "Missing subject param"}, 400)
                return
            try:
                resp = requests.get(
                    f"{PP}/placement/getCurrentLevel",
                    headers=headers,
                    params={"student": sid, "subject": subject},
                    timeout=10,
                )
                if resp.status_code == 200:
                    send_json(self, resp.json())
                else:
                    send_json(self, {"error": f"Status {resp.status_code}"})
            except Exception as e:
                send_json(self, {"error": str(e)})
            return

        # List assignments
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

            # ── Step 1: Check placement level ────────────────────
            placement_grade = None
            try:
                pl_resp = requests.get(
                    f"{PP}/placement/getCurrentLevel",
                    headers=headers,
                    params={"student": sid, "subject": subject},
                    timeout=6,
                )
                if pl_resp.status_code == 200:
                    pl_data = pl_resp.json()
                    placement_grade = pl_data.get("gradeLevel") or pl_data.get("grade")
                    if isinstance(placement_grade, dict):
                        placement_grade = placement_grade.get("level") or placement_grade.get("grade")
            except Exception:
                pass

            # ── Step 2: Create test assignment record ────────────
            payload = {"student": sid, "subject": subject, "grade": grade}
            resp = requests.post(f"{PP}/test-assignments", headers=headers, json=payload, timeout=10)
            try:
                data = resp.json()
            except Exception:
                data = {"status": resp.status_code}

            if resp.status_code not in (200, 201, 204):
                # Assignment creation failed — try screening fallback
                for screen_path in [
                    f"{PP}/screening/assignTest",
                    f"{PP}/screening/tests/assign",
                ]:
                    try:
                        screen_resp = requests.post(
                            screen_path, headers=headers,
                            json={"student": sid, "subject": subject, "grade": grade},
                            timeout=6,
                        )
                        if screen_resp.status_code in (200, 201, 204):
                            data = screen_resp.json()
                            break
                    except Exception:
                        pass
                else:
                    # All assignment methods failed
                    err = ""
                    if isinstance(data, dict):
                        err = data.get("imsx_description") or data.get("error") or data.get("message") or ""
                    hint = ""
                    if placement_grade is not None:
                        try:
                            req_g = int(grade)
                            pl_g = int(placement_grade)
                            if req_g != pl_g:
                                hint = f" Student is placed at Grade {pl_g} in {subject}. Try Grade {pl_g} instead."
                            else:
                                hint = f" Student is at Grade {pl_g} but this test could not be created."
                        except (ValueError, TypeError):
                            pass
                    send_json(self, {
                        "success": False,
                        "error": (err or f"HTTP {resp.status_code}") + hint,
                        "placementGrade": placement_grade,
                        "requestedGrade": grade,
                        "response": data,
                    }, 422)
                    return

            # ── Step 3: Provision on MasteryTrack ────────────────
            # makeExternalTestAssignment authenticates the student on MasteryTrack,
            # returns a test link and credentials so the student can actually take the test.
            lesson_id = ""
            assignment_id = ""
            if isinstance(data, dict):
                lesson_id = data.get("lessonId") or ""
                assignment_id = data.get("assignmentId") or ""

            mt_result = None
            mt_error = ""
            if lesson_id:
                mt_result = _try_mastery_track(headers, sid, lesson_id)

            result = {
                "success": True,
                "message": f"Test assigned ({subject} Grade {grade})",
                "response": data,
            }

            # Include MasteryTrack link/credentials if available
            if mt_result and isinstance(mt_result, dict):
                result["testLink"] = mt_result.get("testLink") or mt_result.get("url") or mt_result.get("link") or ""
                result["credentials"] = mt_result.get("credentials") or {}
                result["masteryTrack"] = mt_result
            elif lesson_id:
                # MasteryTrack provisioning may have failed — note it but don't fail the assignment
                result["masteryTrackNote"] = "Assignment created. MasteryTrack provisioning may need manual setup."

            send_json(self, result)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON", "success": False}, 400)
        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)


def _try_mastery_track(headers, student_id, lesson_id):
    """Try to provision the test on MasteryTrack via lessonPlans/operations.
    Returns the MasteryTrack response dict, or None on failure."""

    # Try multiple endpoint patterns for makeExternalTestAssignment
    operation = {
        "type": "makeExternalTestAssignment",
        "toolProvider": "mastery-track",
        "lessonId": lesson_id,
        "studentId": student_id,
    }

    endpoints = [
        # Lesson plan operations endpoint
        (f"{PP}/lessonPlans/operations", {"operations": [operation]}),
        # Direct operation on specific lesson
        (f"{PP}/lessonPlans/{lesson_id}/operations", {"operations": [operation]}),
        # Alternative: makeExternalTestAssignment as direct endpoint
        (f"{PP}/lessonPlans/makeExternalTestAssignment", {
            "toolProvider": "mastery-track",
            "lessonId": lesson_id,
            "studentId": student_id,
        }),
        # Alternative: test-assignments sub-endpoint
        (f"{PP}/test-assignments/makeExternal", {
            "toolProvider": "mastery-track",
            "lessonId": lesson_id,
            "studentId": student_id,
        }),
    ]

    for url, payload in endpoints:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=8)
            if resp.status_code in (200, 201):
                try:
                    return resp.json()
                except Exception:
                    return {"status": "ok"}
            elif resp.status_code == 404:
                continue  # endpoint doesn't exist, try next
            else:
                # Got a real response (not 404) — stop trying
                try:
                    return resp.json()
                except Exception:
                    return {"error": f"HTTP {resp.status_code}"}
        except Exception:
            continue

    return None
