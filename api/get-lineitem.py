"""GET /api/get-lineitem?id=... — Get assessmentLineItem by ID"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        ali_id = params.get("id", "")
        
        if not ali_id:
            send_json(self, {"error": "Missing id"}, 400)
            return

        headers = api_headers()
        url = f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentLineItems/{ali_id}"
        
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.get(url, headers=headers, timeout=30)
            
            send_json(self, {
                "status": resp.status_code,
                "response": resp.json() if resp.status_code == 200 else resp.text[:500]
            })
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
