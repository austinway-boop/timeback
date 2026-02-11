"""GET /api/course-content?courseId=...&userId=...&enrollmentId=...

Fetches course lesson plan tree and progress from the PowerPath API,
plus classes and line items from OneRoster.
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import (
    API_BASE, api_headers, send_json, get_query_params,
    fetch_with_params, fetch_one,
)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "").strip()
        user_id = params.get("userId", "").strip()
        enrollment_id = params.get("enrollmentId", "").strip()

        if not course_id:
            send_json(self, {"error": "Need courseId"}, 400)
            return

        result = {
            "lessonPlan": None,
            "courseProgress": None,
            "classes": [],
            "lineItems": [],
        }

        try:
            headers = api_headers()

            # ── 1. PowerPath: Get lesson plan tree for course + student ──
            if user_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/{course_id}/{user_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["lessonPlan"] = resp.json()
                except Exception:
                    pass

            # ── 2. PowerPath: Get course progress for student ──
            if user_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/getCourseProgress/{course_id}/student/{user_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["courseProgress"] = resp.json()
                except Exception:
                    pass

            # ── 3. OneRoster: Get classes for this course ──
            try:
                data, st = fetch_one(
                    f"/ims/oneroster/rostering/v1p2/courses/{course_id}/classes"
                )
                if data and st == 200:
                    classes = data.get("classes", [])
                    if not classes:
                        for v in data.values():
                            if isinstance(v, list):
                                classes = v
                                break
                    result["classes"] = [
                        {
                            "sourcedId": c.get("sourcedId", ""),
                            "title": c.get("title", ""),
                            "subjects": c.get("subjects", []),
                            "status": c.get("status", ""),
                        }
                        for c in classes
                        if c.get("title") and "SAFE TO DELETE" not in c.get("title", "")
                    ]
            except Exception:
                pass

            # ── 4. OneRoster: Get line items for classes ──
            class_ids = [c["sourcedId"] for c in result["classes"] if c.get("sourcedId")]
            for cid in class_ids[:5]:
                try:
                    data, st = fetch_with_params(
                        "/ims/oneroster/gradebook/v1p2/lineItems",
                        {"filter": f"class.sourcedId='{cid}'", "limit": 50},
                    )
                    if data and st == 200:
                        items = data.get("lineItems", [])
                        if not items:
                            for v in data.values():
                                if isinstance(v, list):
                                    items = v
                                    break
                        for li in items:
                            result["lineItems"].append({
                                "sourcedId": li.get("sourcedId", ""),
                                "title": li.get("title", ""),
                                "dueDate": li.get("dueDate", ""),
                                "resultValueMax": li.get("resultValueMax", ""),
                                "status": li.get("status", ""),
                            })
                except Exception:
                    continue

            result["success"] = True
            send_json(self, result)

        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
            send_json(self, result, 500)
