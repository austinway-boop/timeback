"""DELETE /api/delete-result — Delete an assessment result.

Query params:
  id: string (required) - The result sourcedId to delete
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


GRADEBOOK = f"{API_BASE}/ims/oneroster/gradebook/v1p2"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        # Allow GET for easier testing
        self._handle_delete()
    
    def do_DELETE(self):
        self._handle_delete()
    
    def _handle_delete(self):
        params = get_query_params(self)
        result_id = params.get("id", "")
        
        if not result_id:
            send_json(self, {"error": "Missing id parameter"}, 400)
            return

        headers = api_headers()
        url = f"{GRADEBOOK}/assessmentResults/{result_id}"
        
        try:
            resp = requests.delete(url, headers=headers, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.delete(url, headers=headers, timeout=30)
            
            if resp.status_code in (200, 204):
                send_json(self, {
                    "status": "success",
                    "deleted": result_id
                })
            else:
                send_json(self, {
                    "status": "error",
                    "httpStatus": resp.status_code,
                    "body": resp.text[:500]
                }, resp.status_code if resp.status_code < 500 else 502)
                
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
