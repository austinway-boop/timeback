"""PUT /api/update-result — Update an existing assessment result.

Body:
  resultId: string (required) - The sourcedId of the result to update
  score: number (0-100)
  scoreStatus: string (default: "fully graded")
  comment: string (optional)

This updates the PowerPath-created result to mark it complete.
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


GRADEBOOK = f"{API_BASE}/ims/oneroster/gradebook/v1p2"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON body"}, 400)
            return

        result_id = body.get("resultId", "")
        score = body.get("score", 100)
        score_status = body.get("scoreStatus", "fully graded")
        comment = body.get("comment", "")

        if not result_id:
            send_json(self, {"error": "Missing resultId"}, 400)
            return

        headers = api_headers()
        debug = []

        # First, GET the existing result to preserve its data
        get_url = f"{GRADEBOOK}/assessmentResults/{result_id}"
        try:
            resp = requests.get(get_url, headers=headers, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.get(get_url, headers=headers, timeout=30)
            
            debug.append({
                "step": "1_get_existing",
                "url": get_url,
                "status": resp.status_code,
            })
            
            if resp.status_code != 200:
                send_json(self, {
                    "status": "error",
                    "message": f"Result not found ({resp.status_code})",
                    "debug": debug
                }, 404)
                return
                
            existing = resp.json().get("assessmentResult", {})
            
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
            return

        # Now PUT the updated result
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        # Preserve existing metadata but add our fields
        metadata = existing.get("metadata", {}) or {}
        metadata["timeback.completed"] = True
        metadata["timeback.completedAt"] = now
        
        update_payload = {
            "assessmentResult": {
                "sourcedId": result_id,
                "status": "active",
                "student": existing.get("student", {}),
                "assessmentLineItem": existing.get("assessmentLineItem", {}),
                "score": score,
                "scoreStatus": score_status,
                "scoreDate": now,
                "comment": comment or existing.get("comment", ""),
                "metadata": metadata,
                "inProgress": "false",
                "incomplete": "false",
                "late": "false",
                "missing": "false"
            }
        }

        put_url = f"{GRADEBOOK}/assessmentResults/{result_id}"
        try:
            resp = requests.put(put_url, headers=headers, json=update_payload, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.put(put_url, headers=headers, json=update_payload, timeout=30)
            
            debug.append({
                "step": "2_put_update",
                "url": put_url,
                "status": resp.status_code,
                "body": resp.text[:500]
            })
            
            if resp.status_code in (200, 201):
                send_json(self, {
                    "status": "success",
                    "resultId": result_id,
                    "response": resp.json() if resp.text else {},
                    "debug": debug
                })
            else:
                send_json(self, {
                    "status": "error",
                    "message": f"Update failed ({resp.status_code})",
                    "debug": debug
                }, resp.status_code)
                
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
