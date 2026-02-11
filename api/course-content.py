"""GET /api/course-content?enrollmentId=...&userId=... — Fetch course assignments/syllabus from Timeback platform.

Proxies requests to the Timeback server functions at alpha.timeback.com.
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import send_json, get_query_params, get_token

TIMEBACK_BASE = "https://alpha.timeback.com/_serverFn"

# Known Timeback server function endpoints
ENDPOINTS = {
    "assignments": "src_features_courses-explorer_actions_getCourseAssignments_ts--getCourseAssignments_createServerFn_handler",
    "syllabus": "src_features_courses-explorer_actions_getCourseSyllabus_ts--getCourseSyllabus_createServerFn_handler",
    "analytics": "src_features_courses-explorer_actions_getEnrollmentAnalyticsBatch_ts--getEnrollmentAnalyticsBatch_createServerFn_handler",
}


def _call_timeback_fn(fn_name: str, payload: dict) -> tuple:
    """Call a Timeback server function. Returns (data, status_code)."""
    url = f"{TIMEBACK_BASE}/{ENDPOINTS.get(fn_name, fn_name)}"
    
    # Try with our Cognito API token
    try:
        token = get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Try POST (most server functions use POST)
        resp = requests.post(
            url,
            json={"data": payload, "context": {}},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json(), 200

        # Try GET with payload as query param
        payload_str = json.dumps({"data": payload, "context": {}})
        resp2 = requests.get(
            url,
            params={"payload": payload_str, "createServerFn": ""},
            headers=headers,
            timeout=30,
        )
        if resp2.status_code == 200:
            return resp2.json(), 200

        return {"error": f"Timeback returned {resp.status_code}", "detail": resp.text[:500]}, resp.status_code

    except Exception as e:
        return {"error": str(e)}, 500


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        enrollment_id = params.get("enrollmentId", "").strip()
        user_id = params.get("userId", "").strip()
        course_id = params.get("courseId", "").strip()
        fn_type = params.get("type", "assignments").strip()

        if not enrollment_id and not course_id:
            send_json(self, {"error": "Missing enrollmentId or courseId"}, 400)
            return

        results = {}

        # Try to fetch assignments
        if fn_type in ("assignments", "all"):
            payload = {}
            if enrollment_id:
                payload["enrollmentId"] = enrollment_id
            if course_id:
                payload["courseId"] = course_id
            if user_id:
                payload["userId"] = user_id

            data, status = _call_timeback_fn("assignments", payload)
            results["assignments"] = data if status == 200 else {"error": f"Status {status}", "raw": data}

        # Try to fetch syllabus
        if fn_type in ("syllabus", "all"):
            payload = {}
            if course_id:
                payload["courseId"] = course_id
            if enrollment_id:
                payload["enrollmentId"] = enrollment_id

            data, status = _call_timeback_fn("syllabus", payload)
            results["syllabus"] = data if status == 200 else {"error": f"Status {status}", "raw": data}

        # Try analytics batch
        if fn_type in ("analytics", "all"):
            payload = {"enrollmentIds": [enrollment_id]} if enrollment_id else {}
            data, status = _call_timeback_fn("analytics", payload)
            results["analytics"] = data if status == 200 else {"error": f"Status {status}", "raw": data}

        results["success"] = True
        send_json(self, results)
