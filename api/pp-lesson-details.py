"""GET /api/pp-lesson-details?lessonId=... — Get PowerPath lesson details.

Tries various ID formats to find the lesson.
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        lesson_id = params.get("lessonId", "")
        student_id = params.get("studentId", "")
        
        if not lesson_id:
            send_json(self, {"error": "Missing lessonId"}, 400)
            return

        headers = api_headers()
        results = []

        # Try various endpoints
        endpoints = [
            f"/powerpath/getLessonDetails?lessonId={lesson_id}",
            f"/powerpath/lessons/{lesson_id}",
            f"/powerpath/lessonPlans/lessons/{lesson_id}",
        ]
        
        if student_id:
            endpoints.append(f"/powerpath/getAssessmentProgress?student={student_id}&lesson={lesson_id}")

        for ep in endpoints:
            url = f"{API_BASE}{ep}"
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                results.append({
                    "endpoint": ep,
                    "status": resp.status_code,
                    "body": resp.text[:500] if resp.text else ""
                })
            except Exception as e:
                results.append({"endpoint": ep, "error": str(e)})

        # Also try POST getLessonDetails (some APIs expect POST)
        url = f"{API_BASE}/powerpath/getLessonDetails"
        try:
            resp = requests.post(url, headers=headers, json={"lessonId": lesson_id}, timeout=15)
            results.append({
                "endpoint": "POST /powerpath/getLessonDetails",
                "status": resp.status_code,
                "body": resp.text[:500] if resp.text else ""
            })
        except Exception as e:
            results.append({"endpoint": "POST /powerpath/getLessonDetails", "error": str(e)})

        send_json(self, {"results": results})
