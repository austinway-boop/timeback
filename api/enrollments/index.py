"""GET    /api/enrollments?userId=... — Active enrollments for a student.
POST   /api/enrollments — Enroll a user in a course.
DELETE /api/enrollments — Remove an enrollment.

EduBridge docs:
  GET    /edubridge/enrollments/user/{userId}
  POST   /edubridge/enrollments/enroll/{userId}/{courseId}/{schoolId?}
  DELETE /ims/oneroster/rostering/v1p2/enrollments/{sourcedId}
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, fetch_one, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        user_id = params.get("userId", "")

        if not user_id:
            send_json(self, {"error": "Missing 'userId' query param"}, 400)
            return

        try:
            data, status = fetch_one(f"/edubridge/enrollments/user/{user_id}")
            if data:
                send_json(self, data)
            else:
                send_json(self, {"error": f"HTTP {status}", "enrollments": []}, status)
        except Exception as e:
            send_json(self, {"error": str(e), "enrollments": []}, 500)

    def do_DELETE(self):
        """Remove an enrollment."""
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            body = json.loads(raw) if raw else {}
            enrollment_id = (body.get("sourcedId") or body.get("enrollmentId") or body.get("id") or "").strip()

            if not enrollment_id:
                send_json(self, {"error": "sourcedId is required", "success": False}, 400)
                return

            headers = api_headers()
            deleted = False

            # Try OneRoster DELETE
            try:
                resp = requests.delete(
                    f"{API_BASE}/ims/oneroster/rostering/v1p2/enrollments/{enrollment_id}",
                    headers=headers, timeout=10,
                )
                if resp.status_code in (200, 204):
                    deleted = True
            except Exception:
                pass

            # Try EduBridge unenroll
            if not deleted:
                try:
                    resp = requests.delete(
                        f"{API_BASE}/edubridge/enrollments/{enrollment_id}",
                        headers=headers, timeout=10,
                    )
                    if resp.status_code in (200, 204):
                        deleted = True
                except Exception:
                    pass

            # Try PUT status=tobedeleted (soft delete)
            if not deleted:
                try:
                    resp = requests.put(
                        f"{API_BASE}/ims/oneroster/rostering/v1p2/enrollments/{enrollment_id}",
                        headers=headers,
                        json={"enrollment": {"sourcedId": enrollment_id, "status": "tobedeleted"}},
                        timeout=10,
                    )
                    if resp.status_code in (200, 201, 204):
                        deleted = True
                except Exception:
                    pass

            if deleted:
                send_json(self, {"success": True, "message": "Enrollment removed"})
            else:
                send_json(self, {"success": False, "error": "Could not remove enrollment"}, 422)

        except Exception as e:
            send_json(self, {"success": False, "error": str(e)}, 500)

    def do_POST(self):
        """Enroll a user in a course via EduBridge."""
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            if not raw:
                send_json(self, {"error": "Empty body"}, 400)
                return

            body = json.loads(raw)
            user_id = (body.get("userId") or body.get("studentId") or body.get("student") or "").strip()
            course_id = (body.get("courseId") or body.get("course") or "").strip()
            role = (body.get("role") or "student").strip()

            if not user_id or not course_id:
                send_json(self, {"error": "userId and courseId are required"}, 400)
                return

            headers = api_headers()
            url = f"{API_BASE}/edubridge/enrollments/enroll/{user_id}/{course_id}"

            payload = {"role": role}
            # Pass optional metadata (goals, metrics) if provided
            if body.get("metadata"):
                payload["metadata"] = body["metadata"]

            resp = requests.post(url, headers=headers, json=payload, timeout=15)

            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(url, headers=headers, json=payload, timeout=15)

            try:
                data = resp.json()
            except Exception:
                data = {"status": resp.status_code}

            if resp.status_code in (200, 201):
                send_json(self, {"success": True, "enrollment": data.get("data", data)}, 201)
            else:
                err = ""
                if isinstance(data, dict):
                    err = data.get("error") or data.get("message") or data.get("imsx_description") or ""
                send_json(self, {
                    "success": False,
                    "error": err or f"HTTP {resp.status_code}",
                    "response": data,
                }, resp.status_code if resp.status_code >= 400 else 422)

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON"}, 400)
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
