"""GET /api/get-result?id=... — Get a single assessment result by ID."""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        result_id = params.get("id", "")
        
        if not result_id:
            send_json(self, {"error": "Missing id parameter"}, 400)
            return
        
        headers = api_headers()
        
        # Try to get the specific assessment result
        url = f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentResults/{result_id}"
        
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.get(url, headers=headers, timeout=30)
            
            if resp.status_code == 200:
                data = resp.json()
                send_json(self, {
                    "found": True,
                    "url": url,
                    "result": data
                })
            else:
                send_json(self, {
                    "found": False,
                    "url": url,
                    "status": resp.status_code,
                    "body": resp.text[:500]
                }, resp.status_code if resp.status_code != 404 else 200)
                
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
