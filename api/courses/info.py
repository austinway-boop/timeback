"""GET /api/course-info?courseId=... — Fetch course details + component count

Returns the course metadata and the total number of course components (lessons/units).
Used to backfill totalLessons for AP courses that don't have it in enrollment data.
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_one, fetch_all_paginated, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "")

        if not course_id:
            send_json(self, {"error": "Missing 'courseId' query param"}, 400)
            return

        try:
            total_lessons = 0

            # 1. Try fetching the course directly for metadata
            course_data, status = fetch_one(
                f"/ims/oneroster/rostering/v1p2/courses/{course_id}"
            )
            metadata = {}
            if course_data:
                # OneRoster wraps in { "course": { ... } }
                course_obj = course_data.get("course", course_data)
                metadata = course_obj.get("metadata", {})
                metrics = metadata.get("metrics", {})
                total_lessons = (
                    metrics.get("totalLessons")
                    or metrics.get("totalUnits")
                    or metadata.get("totalLessons")
                    or metadata.get("totalUnits")
                    or course_obj.get("totalLessons")
                    or course_obj.get("totalUnits")
                    or 0
                )

            # 2. If still 0, count course components
            if not total_lessons:
                components = fetch_all_paginated(
                    f"/ims/oneroster/rostering/v1p2/courses/components?filter=course.sourcedId%3D'{course_id}'",
                    "courseComponents",
                )
                if components:
                    total_lessons = len(components)

            send_json(self, {
                "courseId": course_id,
                "totalLessons": total_lessons,
                "metadata": metadata,
            })
        except Exception as e:
            send_json(self, {"error": str(e), "totalLessons": 0}, 500)
