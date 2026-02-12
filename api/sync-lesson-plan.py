"""POST /api/sync-lesson-plan — Sync a lesson plan via PowerPath API.

Body:
  lessonPlanId: string (required) - The lesson plan ID to sync

Endpoints per docs:
  POST /powerpath/lessonPlans/{lessonPlanId}/operations/sync
  (Applies only pending operations incrementally)
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

        lesson_plan_id = body.get("lessonPlanId", "")
        
        if not lesson_plan_id:
            send_json(self, {"error": "Missing lessonPlanId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Try sync endpoint
        sync_url = f"{API_BASE}/powerpath/lessonPlans/{lesson_plan_id}/operations/sync"
        
        try:
            resp = requests.post(sync_url, headers=headers, json={}, timeout=60)
            
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(sync_url, headers=headers, json={}, timeout=60)
            
            debug.append({
                "step": "sync_operations",
                "url": sync_url,
                "status": resp.status_code,
                "body": resp.text[:1000]
            })

            send_json(self, {
                "status": "completed" if resp.status_code in (200, 201, 204) else "error",
                "syncStatus": resp.status_code,
                "debug": debug
            })

        except Exception as e:
            debug.append({"step": "sync_operations", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": str(e),
                "debug": debug
            }, 500)
