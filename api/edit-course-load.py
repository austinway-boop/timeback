"""GET /api/edit-course-load?courseId=...

Loads the editable course structure. If a saved edit exists in KV, returns it.
Otherwise, fetches the PowerPath lesson plan tree (read-only) and transforms
it into our local edit format as the initial seed.
"""

import time
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params
from api._kv import kv_get


def _transform_tree(tree_data, course_id):
    """Transform a PowerPath lesson plan tree into our edit format.

    The tree has top-level subComponents (units), each with their own
    subComponents (lessons), each with componentResources (activities).
    """
    units = []
    sub = tree_data if isinstance(tree_data, list) else tree_data.get("subComponents", [])

    for u_idx, unit in enumerate(sub):
        unit_id = unit.get("sourcedId") or unit.get("id") or f"unit-{u_idx}"
        unit_title = unit.get("title", f"Unit {u_idx + 1}")
        lessons = []

        for l_idx, lesson in enumerate(unit.get("subComponents", [])):
            lesson_id = lesson.get("sourcedId") or lesson.get("id") or f"lesson-{u_idx}-{l_idx}"
            lesson_title = lesson.get("title", f"Lesson {l_idx + 1}")

            # Skip "Advanced Organizer Submission" items
            if "advanced organizer" in lesson_title.lower():
                continue

            activities = []
            for r_idx, res in enumerate(lesson.get("componentResources", [])):
                resource = res.get("resource", res)
                res_id = resource.get("sourcedId") or resource.get("id") or f"res-{u_idx}-{l_idx}-{r_idx}"
                res_title = resource.get("title", "")
                res_url = resource.get("url", "")

                # Determine type from URL or title
                act_type = "other"
                lower_title = res_title.lower()
                lower_url = res_url.lower()
                if "video" in lower_title or "youtube" in lower_url or "vimeo" in lower_url:
                    act_type = "video"
                elif "article" in lower_title or "reading" in lower_title:
                    act_type = "article"
                elif "quiz" in lower_title or "assessment" in lower_title or "test" in lower_title:
                    act_type = "quiz"
                elif res_url:
                    # Try to infer from URL
                    if any(ext in lower_url for ext in [".mp4", ".webm", "youtube", "vimeo"]):
                        act_type = "video"
                    elif any(ext in lower_url for ext in [".pdf", ".html", ".htm"]):
                        act_type = "article"

                activities.append({
                    "id": res_id,
                    "type": act_type,
                    "title": res_title,
                    "sourceType": "powerpath",
                    "url": res_url,
                })

            lessons.append({
                "id": lesson_id,
                "title": lesson_title,
                "sortOrder": l_idx,
                "activities": activities,
            })

        units.append({
            "id": unit_id,
            "title": unit_title,
            "sortOrder": u_idx,
            "lessons": lessons,
        })

    return {
        "courseId": course_id,
        "lastModified": time.time(),
        "units": units,
        "isInitialSeed": True,
    }


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

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        # Check for saved edits in KV first
        saved = kv_get(f"course_edit:{course_id}")
        if saved and isinstance(saved, dict) and saved.get("units"):
            saved["isInitialSeed"] = False
            send_json(self, saved)
            return

        # No saved edits — fetch PowerPath tree as initial seed
        try:
            headers = api_headers()
            resp = requests.get(
                f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}",
                headers=headers,
                timeout=30,
            )

            if resp.status_code != 200:
                send_json(self, {
                    "error": f"Failed to fetch course tree (status {resp.status_code})",
                    "courseId": course_id,
                    "units": [],
                }, 502)
                return

            tree_data = resp.json()
            result = _transform_tree(tree_data, course_id)
            send_json(self, result)

        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
