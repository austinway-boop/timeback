"""POST /api/mark-complete — Mark a lesson/item as complete via PowerPath operations API.

Body:
  lessonPlanId: string (required) - The lesson plan ID
  itemId: string (required) - The courseComponent or resource ID to mark complete
  studentId: string (optional) - Student ID for context

Docs: https://docs.timeback.com/beta/build-on-timeback/clients/powerpath
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
        item_id = body.get("itemId", "")
        student_id = body.get("studentId", "")

        if not lesson_plan_id or not item_id:
            send_json(self, {"error": "Missing lessonPlanId or itemId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Call PowerPath operations API to mark item complete
        # POST /powerpath/lessonPlans/{lessonPlanId}/operations
        operations_url = f"{API_BASE}/powerpath/lessonPlans/{lesson_plan_id}/operations"
        
        payload = {
            "operations": [
                {
                    "type": "complete",
                    "itemId": item_id
                }
            ]
        }

        try:
            resp = requests.post(
                operations_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(operations_url, headers=headers, json=payload, timeout=30)
            
            debug.append({
                "step": "powerpath_operations",
                "url": operations_url,
                "payload": payload,
                "status": resp.status_code,
                "body": resp.text[:500]
            })

            if resp.status_code in (200, 201, 204):
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                send_json(self, {
                    "status": "success",
                    "message": f"Marked {item_id} as complete",
                    "response": data,
                    "debug": debug
                })
            else:
                send_json(self, {
                    "status": "error",
                    "message": f"PowerPath operations failed ({resp.status_code})",
                    "debug": debug
                }, resp.status_code if resp.status_code < 500 else 502)

        except Exception as e:
            debug.append({"step": "powerpath_operations", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": str(e),
                "debug": debug
            }, 500)
