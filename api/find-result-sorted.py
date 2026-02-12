"""GET /api/find-result-sorted — Try different sort orders to find recent results."""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        result_id = params.get("id", "68580cc9-f0f2-0ed5-483f-80307467f4ab")
        
        headers = api_headers()
        path = "/ims/oneroster/gradebook/v1p2/assessmentResults"
        url = f"{API_BASE}{path}"
        
        results = {}
        
        # Try different sort orders
        sort_options = [
            {"sort": "dateLastModified", "orderBy": "desc"},
            {"sort": "scoreDate", "orderBy": "desc"},
            {},  # default
        ]
        
        for i, sort_params in enumerate(sort_options):
            try:
                query = {"limit": 50}
                query.update(sort_params)
                
                resp = requests.get(url, headers=headers, params=query, timeout=30)
                
                key = f"sort_{i}_{sort_params.get('sort', 'default')}"
                results[key] = {
                    "params": query,
                    "status": resp.status_code
                }
                
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("assessmentResults", [])
                    results[key]["count"] = len(items)
                    
                    # Check for our result
                    found = [r for r in items if r.get("sourcedId") == result_id]
                    results[key]["found"] = len(found) > 0
                    
                    # Show first few with dates
                    results[key]["first_3"] = [
                        {
                            "id": r.get("sourcedId", "")[:20],
                            "date": r.get("dateLastModified", r.get("scoreDate", ""))
                        }
                        for r in items[:3]
                    ]
                else:
                    results[key]["body"] = resp.text[:300]
                    
            except Exception as e:
                results[f"sort_{i}"] = {"error": str(e)}
        
        send_json(self, {
            "searching_for": result_id,
            "results": results
        })
