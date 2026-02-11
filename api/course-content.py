"""GET /api/course-content?courseId=...&enrollmentId=...&userId=...

Fetches course content from the OneRoster API:
1. Classes for the course
2. Line items (assignments) filtered by class.sourcedId
3. Resources (QTI content items)
4. Student results
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import (
    API_BASE, api_headers, send_json, get_query_params,
    fetch_with_params, fetch_all_paginated, fetch_one,
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
        enrollment_id = params.get("enrollmentId", "").strip()
        user_id = params.get("userId", "").strip()

        if not course_id:
            send_json(self, {"error": "Need courseId"}, 400)
            return

        result = {"classes": [], "lineItems": [], "resources": [], "results": []}

        try:
            # ── 1. Get classes for this course ──
            # Use the direct course-classes endpoint (confirmed working)
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
                            "classType": c.get("classType", ""),
                            "subjects": c.get("subjects", []),
                            "status": c.get("status", ""),
                        }
                        for c in classes
                    ]
            except Exception:
                pass

            class_ids = [c["sourcedId"] for c in result["classes"] if c.get("sourcedId")]

            # ── 2. Get line items for each class ──
            # Filter by class.sourcedId (NOT courseSourcedId - that doesn't exist)
            for cid in class_ids[:5]:
                try:
                    data, st = fetch_with_params(
                        "/ims/oneroster/gradebook/v1p2/lineItems",
                        {"filter": f"class.sourcedId='{cid}'", "limit": 100},
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
                                "description": li.get("description", ""),
                                "assignDate": li.get("assignDate", ""),
                                "dueDate": li.get("dueDate", ""),
                                "resultValueMin": li.get("resultValueMin", ""),
                                "resultValueMax": li.get("resultValueMax", ""),
                                "status": li.get("status", ""),
                                "category": (li.get("category", {}) or {}).get("sourcedId", ""),
                            })
                except Exception:
                    continue

            # ── 3. Get resources ──
            # Resources contain the actual QTI content items (questions, assessments)
            try:
                data, st = fetch_with_params(
                    "/ims/oneroster/rostering/v1p2/resources",
                    {"limit": 100},
                )
                if data and st == 200:
                    all_resources = data.get("resources", [])
                    if not all_resources:
                        for v in data.values():
                            if isinstance(v, list):
                                all_resources = v
                                break

                    # Filter resources relevant to this course's subjects
                    course_data, _ = fetch_one(
                        f"/ims/oneroster/rostering/v1p2/courses/{course_id}"
                    )
                    course_subjects = []
                    if course_data:
                        c_obj = course_data.get("course", course_data)
                        course_subjects = [s.lower() for s in (c_obj.get("subjects", []) or [])]
                        course_title = (c_obj.get("title", "") or "").lower()

                    for res in all_resources:
                        meta = res.get("metadata", {}) or {}
                        res_subject = (meta.get("subject", "") or "").lower()
                        res_title = (res.get("title", "") or "").lower()

                        # Match by subject or title keywords
                        relevant = False
                        for subj in course_subjects:
                            if subj in res_subject or subj in res_title:
                                relevant = True
                                break
                        if not relevant and course_title:
                            keywords = [w for w in course_title.split() if len(w) > 3]
                            for kw in keywords:
                                if kw in res_subject or kw in res_title:
                                    relevant = True
                                    break

                        if relevant:
                            result["resources"].append({
                                "sourcedId": res.get("sourcedId", ""),
                                "title": res.get("title", ""),
                                "type": meta.get("type", ""),
                                "subject": meta.get("subject", ""),
                                "difficulty": meta.get("difficulty", ""),
                                "xp": meta.get("xp", 0),
                                "url": meta.get("url", ""),
                                "grade": meta.get("grade", ""),
                                "questionType": meta.get("questionType", ""),
                            })

                        if len(result["resources"]) >= 50:
                            break
            except Exception:
                pass

            # ── 4. Get student results for classes in this course ──
            if user_id and class_ids:
                try:
                    for cid in class_ids[:3]:
                        data, st = fetch_with_params(
                            "/ims/oneroster/gradebook/v1p2/results",
                            {
                                "filter": f"student.sourcedId='{user_id}' AND class.sourcedId='{cid}'",
                                "limit": 100,
                            },
                        )
                        if data and st == 200:
                            res_list = data.get("results", [])
                            if not res_list:
                                for v in data.values():
                                    if isinstance(v, list):
                                        res_list = v
                                        break
                            for r in res_list:
                                result["results"].append({
                                    "sourcedId": r.get("sourcedId", ""),
                                    "score": r.get("score", ""),
                                    "scoreStatus": r.get("scoreStatus", ""),
                                    "scoreDate": r.get("scoreDate", ""),
                                    "comment": r.get("comment", ""),
                                    "lineItemSourcedId": (r.get("lineItem", {}) or {}).get("sourcedId", ""),
                                })
                except Exception:
                    pass

            result["success"] = True
            result["counts"] = {
                "classes": len(result["classes"]),
                "lineItems": len(result["lineItems"]),
                "resources": len(result["resources"]),
                "results": len(result["results"]),
            }
            send_json(self, result)

        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
            send_json(self, result, 500)
