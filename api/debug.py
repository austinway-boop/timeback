"""GET /api/debug?email=... — Debug endpoint to trace the full API pipeline.

Shows raw responses from each step so we can see exactly what Timeback returns.
"""

import json
from http.server import BaseHTTPRequestHandler
from api._helpers import (
    fetch_with_params, fetch_one, parse_user,
    send_json, get_query_params, api_headers, API_BASE,
)
import requests


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        email = params.get("email", "").strip()

        if not email:
            send_json(self, {"error": "Missing 'email' query param"}, 400)
            return

        result = {"email": email, "steps": {}}

        # Step 1: User lookup
        try:
            data, status = fetch_with_params(
                "/ims/oneroster/rostering/v1p2/users",
                {"filter": f"email='{email}'", "limit": 5},
            )
            result["steps"]["1_user_lookup"] = {
                "status": status,
                "raw_keys": list(data.keys()) if data else None,
                "raw_response": data,
            }

            # Extract user
            user = None
            if data:
                users_list = data.get("users", [])
                if not users_list:
                    for key in data:
                        if isinstance(data[key], list) and data[key]:
                            users_list = data[key]
                            break
                if users_list:
                    user = users_list[0]
                    result["steps"]["1_user_parsed"] = parse_user(user)

        except Exception as e:
            result["steps"]["1_user_lookup"] = {"error": str(e)}

        if not user:
            result["conclusion"] = "User not found by email filter"
            send_json(self, result)
            return

        sourced_id = user.get("sourcedId", "")
        result["sourcedId"] = sourced_id

        # Step 2: EduBridge enrollments
        try:
            headers = api_headers()
            url = f"{API_BASE}/edubridge/enrollments/user/{sourced_id}"
            resp = requests.get(url, headers=headers, timeout=30)

            raw_text = resp.text[:5000]  # First 5KB
            try:
                raw_json = resp.json()
            except Exception:
                raw_json = None

            result["steps"]["2_enrollments"] = {
                "status": resp.status_code,
                "raw_type": type(raw_json).__name__ if raw_json is not None else "parse_error",
                "raw_keys": list(raw_json.keys()) if isinstance(raw_json, dict) else None,
                "raw_length": len(raw_json) if isinstance(raw_json, list) else None,
                "raw_response": raw_json,
                "raw_text_preview": raw_text[:500] if not raw_json else None,
            }
        except Exception as e:
            result["steps"]["2_enrollments"] = {"error": str(e)}

        # Step 3: OneRoster enrollments as fallback check
        try:
            data3, status3 = fetch_with_params(
                "/ims/oneroster/rostering/v1p2/enrollments",
                {"filter": f"user.sourcedId='{sourced_id}'", "limit": 50},
            )
            enrollments_list = []
            if data3:
                enrollments_list = data3.get("enrollments", [])
                if not enrollments_list:
                    for key in data3:
                        if isinstance(data3[key], list):
                            enrollments_list = data3[key]
                            break

            result["steps"]["3_oneroster_enrollments"] = {
                "status": status3,
                "count": len(enrollments_list),
                "sample": enrollments_list[:3] if enrollments_list else [],
            }
        except Exception as e:
            result["steps"]["3_oneroster_enrollments"] = {"error": str(e)}

        send_json(self, result)
