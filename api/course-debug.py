"""GET /api/course-debug?courseId=...&enrollmentId=...&userId=...

Tries EVERY possible API path to find course content/units/lessons.
Returns what each path returns so we can find the right one.
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "").strip()
        enrollment_id = params.get("enrollmentId", "").strip()
        user_id = params.get("userId", "").strip()

        results = {}
        headers = api_headers()

        paths_to_try = []

        # OneRoster rostering paths
        if course_id:
            paths_to_try.extend([
                ("oneroster_course", f"/ims/oneroster/rostering/v1p2/courses/{course_id}"),
                ("oneroster_classes_filter", f"/ims/oneroster/rostering/v1p2/classes?filter=course.sourcedId='{course_id}'&limit=10"),
                ("oneroster_classes_for_course", f"/ims/oneroster/rostering/v1p2/courses/{course_id}/classes"),
            ])

        # OneRoster gradebook paths
        if course_id:
            paths_to_try.extend([
                ("gradebook_lineItems_v1p2", f"/ims/oneroster/gradebook/v1p2/lineItems?filter=course.sourcedId='{course_id}'&limit=10"),
                ("gradebook_lineItems_v1p2_alt", f"/ims/oneroster/v1p2/lineItems?limit=5"),
                ("gradebook_results_v1p2", f"/ims/oneroster/gradebook/v1p2/results?limit=5"),
                ("gradebook_categories", f"/ims/oneroster/gradebook/v1p2/categories?limit=5"),
            ])

        # OneRoster resource paths
        if course_id:
            paths_to_try.extend([
                ("resources_for_course", f"/ims/oneroster/resources/v1p2/courseResources?filter=course.sourcedId='{course_id}'&limit=10"),
                ("resources_all", f"/ims/oneroster/resources/v1p2/resources?limit=5"),
                ("resources_v1p2", f"/ims/oneroster/v1p2/resources?limit=5"),
                ("resources_course_direct", f"/ims/oneroster/rostering/v1p2/courses/{course_id}/resources"),
            ])

        # EduBridge paths
        if course_id:
            paths_to_try.extend([
                ("edubridge_course", f"/edubridge/courses/{course_id}"),
                ("edubridge_course_units", f"/edubridge/courses/{course_id}/units"),
                ("edubridge_course_lessons", f"/edubridge/courses/{course_id}/lessons"),
                ("edubridge_course_syllabus", f"/edubridge/courses/{course_id}/syllabus"),
                ("edubridge_course_content", f"/edubridge/courses/{course_id}/content"),
                ("edubridge_course_modules", f"/edubridge/courses/{course_id}/modules"),
                ("edubridge_course_assignments", f"/edubridge/courses/{course_id}/assignments"),
                ("edubridge_course_curriculum", f"/edubridge/courses/{course_id}/curriculum"),
            ])

        if enrollment_id:
            paths_to_try.extend([
                ("edubridge_enrollment", f"/edubridge/enrollments/{enrollment_id}"),
                ("edubridge_enrollment_content", f"/edubridge/enrollments/{enrollment_id}/content"),
                ("edubridge_enrollment_progress", f"/edubridge/enrollments/{enrollment_id}/progress"),
                ("edubridge_enrollment_lessons", f"/edubridge/enrollments/{enrollment_id}/lessons"),
                ("edubridge_enrollment_units", f"/edubridge/enrollments/{enrollment_id}/units"),
                ("edubridge_enrollment_assignments", f"/edubridge/enrollments/{enrollment_id}/assignments"),
            ])

        if user_id:
            paths_to_try.extend([
                ("user_results", f"/ims/oneroster/gradebook/v1p2/results?filter=student.sourcedId='{user_id}'&limit=10"),
            ])

        # Generic content/curriculum paths
        if course_id:
            paths_to_try.extend([
                ("api_v1_courses", f"/api/v1/courses/{course_id}"),
                ("api_v1_courses_content", f"/api/v1/courses/{course_id}/content"),
                ("api_v1_courses_units", f"/api/v1/courses/{course_id}/units"),
                ("api_v1_courses_lessons", f"/api/v1/courses/{course_id}/lessons"),
                ("content_courses", f"/content/courses/{course_id}"),
                ("curriculum_courses", f"/curriculum/courses/{course_id}"),
                ("powerpath_course", f"/powerpath/courses/{course_id}"),
                ("powerpath_course_units", f"/powerpath/courses/{course_id}/units"),
            ])

        # Try each path
        for name, path in paths_to_try:
            try:
                url = f"{API_BASE}{path}"
                resp = requests.get(url, headers=headers, timeout=15)
                status = resp.status_code

                body = None
                preview = ""
                try:
                    body = resp.json()
                    # Truncate large responses
                    preview = json.dumps(body)[:2000]
                except Exception:
                    preview = resp.text[:500]

                results[name] = {
                    "status": status,
                    "has_data": body is not None and status == 200,
                    "type": type(body).__name__ if body is not None else "text",
                    "keys": list(body.keys()) if isinstance(body, dict) else None,
                    "length": len(body) if isinstance(body, list) else None,
                    "preview": preview,
                }
            except Exception as e:
                results[name] = {"status": 0, "error": str(e)}

        send_json(self, {
            "courseId": course_id,
            "enrollmentId": enrollment_id,
            "userId": user_id,
            "paths_tried": len(paths_to_try),
            "results": results,
        })
