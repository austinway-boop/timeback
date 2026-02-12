"""GET /api/test-results — Debug endpoint to test gradebook result fetching.

Tests both the assessmentResults and results endpoints.
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        user_id = params.get("userId", "")
        
        headers = api_headers()
        results = {}
        
        # Test paths
        test_paths = [
            "/ims/oneroster/gradebook/v1p2/assessmentResults",
            "/ims/oneroster/gradebook/v1p2/results", 
            "/ims/oneroster/v1p2/results",
            "/ims/oneroster/rostering/v1p2/results",
        ]
        
        for path in test_paths:
            try:
                url = f"{API_BASE}{path}"
                params_dict = {"limit": 10}
                if user_id:
                    params_dict["filter"] = f"student.sourcedId='{user_id}'"
                
                resp = requests.get(url, headers=headers, params=params_dict, timeout=30)
                results[path] = {
                    "status": resp.status_code,
                    "url": url,
                }
                
                if resp.status_code == 200:
                    data = resp.json()
                    # Get the count and first few items
                    for key in ["assessmentResults", "results"]:
                        if key in data and isinstance(data[key], list):
                            results[path]["collection"] = key
                            results[path]["count"] = len(data[key])
                            results[path]["sample"] = data[key][:2] if data[key] else []
                            break
                    else:
                        results[path]["raw_keys"] = list(data.keys())
                        # Try to find any list
                        for k, v in data.items():
                            if isinstance(v, list):
                                results[path]["found_list"] = k
                                results[path]["count"] = len(v)
                                results[path]["sample"] = v[:2] if v else []
                                break
                else:
                    try:
                        results[path]["body"] = resp.text[:500]
                    except:
                        pass
                        
            except Exception as e:
                results[path] = {"error": str(e)}
        
        send_json(self, {
            "userId": user_id,
            "apiBase": API_BASE,
            "results": results
        })
