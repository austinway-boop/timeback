"""GET /api/find-result?id=...&search_pages=... — Search for a result across pages."""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        result_id = params.get("id", "68580cc9-f0f2-0ed5-483f-80307467f4ab")
        max_pages = int(params.get("pages", "5"))
        
        headers = api_headers()
        
        path = "/ims/oneroster/gradebook/v1p2/assessmentResults"
        limit = 100
        found = None
        pages_searched = 0
        total_results = 0
        
        for page in range(max_pages):
            offset = page * limit
            try:
                url = f"{API_BASE}{path}"
                resp = requests.get(
                    url, 
                    headers=headers, 
                    params={"limit": limit, "offset": offset},
                    timeout=60
                )
                
                if resp.status_code != 200:
                    break
                
                data = resp.json()
                results = data.get("assessmentResults", [])
                
                if not results:
                    break
                
                pages_searched = page + 1
                total_results += len(results)
                
                # Search for our result
                for r in results:
                    if r.get("sourcedId") == result_id:
                        found = r
                        break
                
                if found:
                    break
                    
                # If we got less than limit, we've reached the end
                if len(results) < limit:
                    break
                    
            except Exception as e:
                send_json(self, {"error": str(e)}, 500)
                return
        
        send_json(self, {
            "searching_for": result_id,
            "pages_searched": pages_searched,
            "total_results_scanned": total_results,
            "found": found is not None,
            "result": found
        })
