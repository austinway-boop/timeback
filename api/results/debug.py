"""GET /api/debug-results?userId=... — Debug the results fetching logic."""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        user_id = params.get("userId", "")
        limit = int(params.get("limit", "50"))
        
        headers = api_headers()
        debug_info = {}
        
        # Test 1: assessmentResults with filter
        path1 = "/ims/oneroster/gradebook/v1p2/assessmentResults"
        filter_str = f"student.sourcedId='{user_id}'" if user_id else None
        
        try:
            url = f"{API_BASE}{path1}"
            query_params = {"limit": limit}
            if filter_str:
                query_params["filter"] = filter_str
            
            debug_info["request_1"] = {
                "url": url,
                "params": query_params
            }
            
            resp = requests.get(url, headers=headers, params=query_params, timeout=60)
            debug_info["response_1"] = {
                "status": resp.status_code,
                "url_actual": resp.url,
            }
            
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("assessmentResults", [])
                debug_info["response_1"]["count"] = len(results)
                debug_info["response_1"]["first_3"] = results[:3]
                
                # Check if our test result is in there
                test_id = "68580cc9-f0f2-0ed5-483f-80307467f4ab"
                found = [r for r in results if r.get("sourcedId") == test_id]
                debug_info["response_1"]["test_result_found"] = len(found) > 0
            else:
                debug_info["response_1"]["body"] = resp.text[:500]
                
        except Exception as e:
            debug_info["error_1"] = str(e)
        
        # Test 2: assessmentResults WITHOUT filter (to see if test result exists at all)
        try:
            url2 = f"{API_BASE}{path1}"
            query_params2 = {"limit": limit}
            
            debug_info["request_2_no_filter"] = {
                "url": url2,
                "params": query_params2
            }
            
            resp2 = requests.get(url2, headers=headers, params=query_params2, timeout=60)
            debug_info["response_2"] = {
                "status": resp2.status_code,
            }
            
            if resp2.status_code == 200:
                data2 = resp2.json()
                results2 = data2.get("assessmentResults", [])
                debug_info["response_2"]["count"] = len(results2)
                
                # Check if our test result is in there
                test_id = "68580cc9-f0f2-0ed5-483f-80307467f4ab"
                found2 = [r for r in results2 if r.get("sourcedId") == test_id]
                debug_info["response_2"]["test_result_found"] = len(found2) > 0
                if found2:
                    debug_info["response_2"]["test_result"] = found2[0]
                
        except Exception as e:
            debug_info["error_2"] = str(e)
        
        send_json(self, debug_info)
