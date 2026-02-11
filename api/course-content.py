"""GET /api/course-content?courseId=...&userId=...

Fetches the lesson plan tree and student progress from the PowerPath API.

Endpoints used:
  /powerpath/lessonPlans/tree/{courseId} — full tree (units → lessons → items)
  /powerpath/lessonPlans/{courseId}/{userId} — student-specific lesson plan
  /powerpath/lessonPlans/getCourseProgress/{courseId}/student/{userId} — progress
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


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

        if not course_id:
            send_json(self, {"error": "Need courseId"}, 400)
            return

        result = {"lessonPlan": None, "courseProgress": None, "tree": None}

        try:
            headers = api_headers()

            # 1. Student-specific lesson plan (best: personalized + has completion status)
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

            # 2. Full lesson plan tree (fallback: structure without student-specific status)
            if not result["lessonPlan"]:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["tree"] = resp.json()
                except Exception:
                    pass

            # 3. Student progress (completion status for assessments)
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

            result["success"] = True
            send_json(self, result)

        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
            send_json(self, result, 500)
