"""GET /api/course-content?courseId=...&enrollmentId=...&userId=...

Fetches course units, lessons, and assignments from the OneRoster API.
Queries multiple OneRoster paths to find content for a given course.
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import (
    API_BASE, api_headers, send_json, get_query_params,
    fetch_with_params, fetch_all_paginated, fetch_one,
)


def _try_fetch(path, params=None):
    """Try fetching from an API path, return (data, status) or (None, 0) on failure."""
    try:
        if params:
            data, status = fetch_with_params(path, params)
        else:
            data, status = fetch_one(path)
        return data, status
    except Exception:
        return None, 0


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
        enrollment_id = params.get("enrollmentId", "").strip()
        user_id = params.get("userId", "").strip()

        if not course_id and not enrollment_id:
            send_json(self, {"error": "Need courseId or enrollmentId"}, 400)
            return

        result = {"units": [], "resources": [], "lineItems": [], "classes": [], "results": []}

        try:
            headers = api_headers()

            # 1. Get classes for this course
            classes = []
            if course_id:
                # Try filtering classes by course
                data, st = _try_fetch(
                    "/ims/oneroster/rostering/v1p2/classes",
                    {"filter": f"course.sourcedId='{course_id}'", "limit": 100}
                )
                if data and st == 200:
                    classes = data.get("classes", [])
                    if not classes:
                        for v in data.values():
                            if isinstance(v, list):
                                classes = v
                                break

                # Fallback: fetch all classes and filter client-side
                if not classes:
                    all_classes = fetch_all_paginated(
                        "/ims/oneroster/rostering/v1p2/classes", "classes"
                    )
                    classes = [
                        c for c in all_classes
                        if (c.get("course", {}) or {}).get("sourcedId") == course_id
                    ]

            result["classes"] = [
                {
                    "sourcedId": c.get("sourcedId", ""),
                    "title": c.get("title", ""),
                    "classCode": c.get("classCode", ""),
                    "classType": c.get("classType", ""),
                    "status": c.get("status", ""),
                }
                for c in classes
            ]

            class_ids = [c.get("sourcedId", "") for c in classes if c.get("sourcedId")]

            # 2. Get line items (assignments/tests) for these classes
            line_items = []
            for cid in class_ids[:10]:  # limit to 10 classes
                data, st = _try_fetch(
                    "/ims/oneroster/gradebook/v1p2/lineItems",
                    {"filter": f"class.sourcedId='{cid}'", "limit": 100}
                )
                if data and st == 200:
                    items = data.get("lineItems", [])
                    if not items:
                        for v in data.values():
                            if isinstance(v, list):
                                items = v
                                break
                    line_items.extend(items)

            # Fallback: try without gradebook path
            if not line_items:
                for path in ["/ims/oneroster/v1p2/lineItems", "/ims/oneroster/gradebook/v1p2/lineItems"]:
                    try:
                        all_li = fetch_all_paginated(path, "lineItems")
                        if all_li and class_ids:
                            line_items = [
                                li for li in all_li
                                if (li.get("class", {}) or {}).get("sourcedId") in class_ids
                            ]
                        elif all_li:
                            line_items = all_li[:50]  # just return first 50 if no class filter
                        if line_items:
                            break
                    except Exception:
                        continue

            result["lineItems"] = [
                {
                    "sourcedId": li.get("sourcedId", ""),
                    "title": li.get("title", ""),
                    "description": li.get("description", ""),
                    "assignDate": li.get("assignDate", ""),
                    "dueDate": li.get("dueDate", ""),
                    "resultValueMin": li.get("resultValueMin", ""),
                    "resultValueMax": li.get("resultValueMax", ""),
                    "status": li.get("status", ""),
                }
                for li in line_items
            ]

            # 3. Get student results if userId provided
            if user_id:
                for path in ["/ims/oneroster/gradebook/v1p2/results", "/ims/oneroster/v1p2/results"]:
                    data, st = _try_fetch(
                        path,
                        {"filter": f"student.sourcedId='{user_id}'", "limit": 200}
                    )
                    if data and st == 200:
                        results_list = data.get("results", [])
                        if not results_list:
                            for v in data.values():
                                if isinstance(v, list):
                                    results_list = v
                                    break
                        result["results"] = [
                            {
                                "sourcedId": r.get("sourcedId", ""),
                                "lineItemSourcedId": (r.get("lineItem", {}) or {}).get("sourcedId", ""),
                                "score": r.get("score", ""),
                                "scoreStatus": r.get("scoreStatus", ""),
                                "scoreDate": r.get("scoreDate", ""),
                                "comment": r.get("comment", ""),
                                "metadata": r.get("metadata", {}),
                            }
                            for r in results_list
                        ]
                        break

            # 4. Get course resources
            if course_id:
                for path in ["/ims/oneroster/resources/v1p2/courseResources",
                             "/ims/oneroster/v1p2/courseResources"]:
                    data, st = _try_fetch(
                        path,
                        {"filter": f"course.sourcedId='{course_id}'", "limit": 100}
                    )
                    if data and st == 200:
                        resources = data.get("courseResources", [])
                        if not resources:
                            for v in data.values():
                                if isinstance(v, list):
                                    resources = v
                                    break
                        result["resources"] = resources[:50]
                        break

            # 5. Try to get the course itself for any unit/module metadata
            if course_id:
                data, st = _try_fetch(
                    f"/ims/oneroster/rostering/v1p2/courses/{course_id}"
                )
                if data and st == 200:
                    course_obj = data.get("course", data)
                    result["courseDetail"] = course_obj

            # 6. Try EduBridge-specific paths for content
            if enrollment_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/edubridge/enrollments/{enrollment_id}/content",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["eduBridgeContent"] = resp.json()
                except Exception:
                    pass

            if course_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/edubridge/courses/{course_id}/units",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["units"] = resp.json()
                except Exception:
                    pass

                # Also try syllabus/curriculum path
                try:
                    resp = requests.get(
                        f"{API_BASE}/edubridge/courses/{course_id}/syllabus",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["syllabus"] = resp.json()
                except Exception:
                    pass

            result["success"] = True
            send_json(self, result)

        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
            send_json(self, result, 500)
