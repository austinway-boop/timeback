"""POST /api/import-result — Import external test result via PowerPath API.

Body:
  lessonPlanId: string (required) - The lesson plan ID
  studentId: string (required) - Student ID  
  resourceId: string (required) - The courseComponentResource ID (e.g., USHI23-l44-r155857-bank-v1)

Docs: https://docs.timeback.com/beta/api-reference/beyond-ai/powerpath/course-mastery/import-external-test-assignment-results
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
        student_id = body.get("studentId", "")
        resource_id = body.get("resourceId", "")

        if not lesson_plan_id or not student_id or not resource_id:
            send_json(self, {"error": "Missing lessonPlanId, studentId, or resourceId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Try importExternalTestAssignmentResults endpoint
        # Based on pattern: POST /powerpath/assessments/{lessonPlanId}/{studentId}/{resourceId}/importExternalTestAssignmentResults
        import_url = f"{API_BASE}/powerpath/assessments/{lesson_plan_id}/{student_id}/{resource_id}/importExternalTestAssignmentResults"
        
        try:
            resp = requests.post(import_url, headers=headers, json={}, timeout=60)
            
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(import_url, headers=headers, json={}, timeout=60)
            
            debug.append({
                "step": "import_external_results",
                "url": import_url,
                "status": resp.status_code,
                "body": resp.text[:2000]
            })

            if resp.status_code in (200, 201, 204):
                try:
                    data = resp.json()
                except:
                    data = {}
                send_json(self, {
                    "status": "success",
                    "response": data,
                    "debug": debug
                })
            else:
                send_json(self, {
                    "status": "error",
                    "message": f"Import failed ({resp.status_code})",
                    "debug": debug
                }, resp.status_code if resp.status_code < 500 else 502)

        except Exception as e:
            debug.append({"step": "import_external_results", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": str(e),
                "debug": debug
            }, 500)
