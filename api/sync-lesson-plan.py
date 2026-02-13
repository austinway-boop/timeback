"""POST /api/sync-lesson-plan — Sync a lesson plan via PowerPath API.

Body:
  courseId: string - Course ID for course-level sync
  lessonPlanId: string - Lesson plan ID for operations sync

Endpoints per docs:
  POST /powerpath/lessonPlans/course/{courseId}/sync - Full course sync
  POST /powerpath/lessonPlans/{lessonPlanId}/operations/sync - Operations sync
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON body"}, 400)
            return

        course_id = body.get("courseId", "")
        lesson_plan_id = body.get("lessonPlanId", "")
        
        if not course_id and not lesson_plan_id:
            send_json(self, {"error": "Need courseId or lessonPlanId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Try course-level sync first if courseId provided
        if course_id:
            sync_url = f"{API_BASE}/powerpath/lessonPlans/course/{course_id}/sync"
            try:
                resp = requests.post(sync_url, headers=headers, json={}, timeout=90)
                
                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.post(sync_url, headers=headers, json={}, timeout=90)
                
                debug.append({
                    "step": "course_sync",
                    "url": sync_url,
                    "status": resp.status_code,
                    "body": resp.text[:1000]
                })
            except Exception as e:
                debug.append({"step": "course_sync", "error": str(e)})

        # Also try operations sync if lessonPlanId provided
        if lesson_plan_id:
            ops_url = f"{API_BASE}/powerpath/lessonPlans/{lesson_plan_id}/operations/sync"
            try:
                resp = requests.post(ops_url, headers=headers, json={}, timeout=90)
                
                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.post(ops_url, headers=headers, json={}, timeout=90)
                
                debug.append({
                    "step": "operations_sync",
                    "url": ops_url,
                    "status": resp.status_code,
                    "body": resp.text[:1000]
                })
            except Exception as e:
                debug.append({"step": "operations_sync", "error": str(e)})

        send_json(self, {
            "status": "completed",
            "debug": debug
        })
