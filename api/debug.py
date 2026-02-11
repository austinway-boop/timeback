"""GET /api/debug?action=...&userId=... — Debug endpoint to test PowerPath API responses.

Actions:
  list-tests         — GET /powerpath/tests
  list-assignments   — GET /powerpath/test-assignments?userId=...
  user-assignments   — GET /powerpath/test-assignments/user/{userId}
  screening-tests    — GET /powerpath/screening/tests
  user-screenings    — GET /powerpath/screening/tests/user/{userId}
  enrollments        — GET /edubridge/enrollments/user/{userId}
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests
from api._helpers import API_BASE, api_headers, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        action = params.get("action", [""])[0]
        user_id = params.get("userId", [""])[0]

        if not action:
            send_json(self, {"error": "Missing action param", "actions": [
                "list-tests", "list-assignments", "user-assignments",
                "screening-tests", "user-screenings", "enrollments",
            ]})
            return

        headers = api_headers()
        results = {}

        try:
            if action == "list-tests":
                # Try multiple paths for listing available tests
                for path in [
                    "/powerpath/tests",
                    "/powerpath/assessments",
                    "/powerpath/test-assignments/available",
                ]:
                    try:
                        resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=30)
                        results[path] = {"status": resp.status_code}
                        if resp.status_code == 200:
                            results[path]["data"] = resp.json()
                        else:
                            try:
                                results[path]["body"] = resp.text[:500]
                            except:
                                pass
                    except Exception as e:
                        results[path] = {"error": str(e)}

            elif action == "list-assignments" and user_id:
                for field in ["student", "userId", "studentId", "userSourcedId"]:
                    try:
                        resp = requests.get(
                            f"{API_BASE}/powerpath/test-assignments",
                            headers=headers,
                            params={field: user_id},
                            timeout=30,
                        )
                        results[f"GET?{field}"] = {"status": resp.status_code}
                        if resp.status_code == 200:
                            results[f"GET?{field}"]["data"] = resp.json()
                        else:
                            try:
                                results[f"GET?{field}"]["body"] = resp.text[:500]
                            except:
                                pass
                    except Exception as e:
                        results[f"GET?{field}"] = {"error": str(e)}

                # Also try POST with different field names to see what the API says
                for field in ["student", "userId", "studentId"]:
                    try:
                        payload = {field: user_id, "subject": "Math", "grade": "6"}
                        resp = requests.post(
                            f"{API_BASE}/powerpath/test-assignments",
                            headers=headers,
                            json=payload,
                            timeout=30,
                        )
                        results[f"POST.{field}"] = {"status": resp.status_code, "payload": payload}
                        try:
                            results[f"POST.{field}"]["data"] = resp.json()
                        except:
                            results[f"POST.{field}"]["body"] = resp.text[:500]
                    except Exception as e:
                        results[f"POST.{field}"] = {"error": str(e)}

            elif action == "user-assignments" and user_id:
                for path in [
                    f"/powerpath/test-assignments/user/{user_id}",
                    f"/powerpath/users/{user_id}/test-assignments",
                    f"/powerpath/test-assignments/student/{user_id}",
                ]:
                    try:
                        resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=30)
                        results[path] = {"status": resp.status_code}
                        if resp.status_code == 200:
                            results[path]["data"] = resp.json()
                        else:
                            try:
                                results[path]["body"] = resp.text[:500]
                            except:
                                pass
                    except Exception as e:
                        results[path] = {"error": str(e)}

            elif action == "screening-tests":
                for path in [
                    "/powerpath/screening/tests",
                    "/powerpath/screening/tests/available",
                    "/powerpath/screening",
                ]:
                    try:
                        resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=30)
                        results[path] = {"status": resp.status_code}
                        if resp.status_code == 200:
                            results[path]["data"] = resp.json()
                        else:
                            try:
                                results[path]["body"] = resp.text[:500]
                            except:
                                pass
                    except Exception as e:
                        results[path] = {"error": str(e)}

            elif action == "user-screenings" and user_id:
                for path in [
                    f"/powerpath/screening/tests/user/{user_id}",
                    f"/powerpath/screening/user/{user_id}",
                ]:
                    try:
                        resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=30)
                        results[path] = {"status": resp.status_code}
                        if resp.status_code == 200:
                            results[path]["data"] = resp.json()
                        else:
                            try:
                                results[path]["body"] = resp.text[:500]
                            except:
                                pass
                    except Exception as e:
                        results[path] = {"error": str(e)}

            elif action == "enrollments" and user_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/edubridge/enrollments/user/{user_id}",
                        headers=headers, timeout=30,
                    )
                    results["enrollments"] = {"status": resp.status_code}
                    if resp.status_code == 200:
                        data = resp.json()
                        # Extract just mastery test enrollments
                        raw = data.get("data", data.get("enrollments", []))
                        if isinstance(raw, list):
                            mastery = []
                            for e in raw:
                                course = e.get("course", {})
                                meta = (e.get("metadata", {}).get("metrics", {}))
                                cmeta = course.get("metadata", {}).get("metrics", {})
                                title = (course.get("title") or "").lower()
                                is_m = meta.get("courseType") in ("mastery_test", "mastery-test", "masteryTest") \
                                    or cmeta.get("courseType") in ("mastery_test", "mastery-test", "masteryTest") \
                                    or ("mastery" in title and "test" in title)
                                if is_m:
                                    mastery.append({
                                        "enrollmentId": e.get("id") or e.get("sourcedId", ""),
                                        "title": course.get("title", ""),
                                        "subjects": course.get("subjects", []),
                                        "grades": course.get("grades", []),
                                        "status": e.get("status", ""),
                                        "metadata": e.get("metadata", {}),
                                    })
                            results["mastery_tests"] = mastery
                            results["total_enrollments"] = len(raw)
                        else:
                            results["enrollments"]["data"] = data
                except Exception as e:
                    results["enrollments"] = {"error": str(e)}

            else:
                send_json(self, {"error": f"Unknown action or missing userId: {action}"})
                return

        except Exception as e:
            results["fatal_error"] = str(e)

        send_json(self, {"action": action, "userId": user_id, "results": results})
