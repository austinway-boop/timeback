"""GET /api/results-by-ali?ali=... — Get results by assessmentLineItem sourcedId"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        ali = params.get("ali", "")
        student_id = params.get("studentId", "")
        
        if not ali:
            send_json(self, {"error": "Missing ali parameter"}, 400)
            return

        headers = api_headers()
        
        # Try direct query with filter
        url = f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentResults"
        query_params = {
            "limit": 100,
            "filter": f"assessmentLineItem.sourcedId='{ali}'"
        }
        if student_id:
            query_params["filter"] += f" AND student.sourcedId='{student_id}'"
        
        try:
            resp = requests.get(url, headers=headers, params=query_params, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.get(url, headers=headers, params=query_params, timeout=30)
            
            send_json(self, {
                "status": resp.status_code,
                "url": url,
                "filter": query_params["filter"],
                "response": resp.json() if resp.status_code == 200 else resp.text[:500]
            })
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
