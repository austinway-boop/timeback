"""GET /api/courses-search — Search courses with pagination (limit/offset).

Query params:
    q      – search term (filters by title, case-insensitive)
    limit  – max results per page (default 10, max 50)
    offset – number of records to skip (default 0)

Returns: { courses: [...], hasMore: bool }
"""

from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import API_BASE, api_headers, get_query_params, send_json


def _parse_course(raw: dict) -> dict:
    return {
        "sourcedId": raw.get("sourcedId", ""),
        "title": raw.get("title", ""),
        "courseCode": raw.get("courseCode", ""),
        "status": raw.get("status", ""),
        "subjects": raw.get("subjects", []),
        "grades": raw.get("grades", []),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        q = params.get("q", "").strip()
        try:
            limit = min(int(params.get("limit", "10")), 50)
        except ValueError:
            limit = 10
        try:
            offset = max(int(params.get("offset", "0")), 0)
        except ValueError:
            offset = 0

        url = f"{API_BASE}/ims/oneroster/rostering/v1p2/courses"

        try:
            headers = api_headers()

            if q:
                # Attempt OneRoster server-side filter first
                api_params = {
                    "limit": limit,
                    "offset": offset,
                    "filter": f"title~'{q}'",
                }
                resp = requests.get(
                    url, headers=headers, params=api_params, timeout=60
                )

                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.get(
                        url, headers=headers, params=api_params, timeout=60
                    )

                # If filter is supported, use those results
                if resp.status_code == 200:
                    data = resp.json()
                    courses = [_parse_course(c) for c in data.get("courses", [])]
                    has_more = len(courses) == limit
                    send_json(
                        self,
                        {"courses": courses, "hasMore": has_more},
                    )
                    return

                # Fallback: fetch a larger batch and filter in Python
                fb_params = {"limit": 3000, "offset": 0}
                resp = requests.get(
                    url, headers=headers, params=fb_params, timeout=120
                )
                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.get(
                        url, headers=headers, params=fb_params, timeout=120
                    )

                if resp.status_code == 200:
                    data = resp.json()
                    all_courses = data.get("courses", [])
                    q_lower = q.lower()
                    filtered = [
                        c
                        for c in all_courses
                        if q_lower in (c.get("title") or "").lower()
                    ]
                    page = filtered[offset : offset + limit]
                    courses = [_parse_course(c) for c in page]
                    has_more = (offset + limit) < len(filtered)
                    send_json(
                        self,
                        {"courses": courses, "hasMore": has_more},
                    )
                    return

                send_json(
                    self,
                    {"error": "Failed to fetch courses", "courses": [], "hasMore": False},
                    500,
                )
            else:
                # No search query — just paginate via OneRoster native params
                api_params = {"limit": limit, "offset": offset}
                resp = requests.get(
                    url, headers=headers, params=api_params, timeout=60
                )

                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.get(
                        url, headers=headers, params=api_params, timeout=60
                    )

                if resp.status_code != 200:
                    send_json(
                        self,
                        {"error": "Failed to fetch courses", "courses": [], "hasMore": False},
                        500,
                    )
                    return

                data = resp.json()
                courses = [_parse_course(c) for c in data.get("courses", [])]
                has_more = len(courses) == limit
                send_json(self, {"courses": courses, "hasMore": has_more})

        except Exception as e:
            send_json(
                self,
                {"error": str(e), "courses": [], "hasMore": False},
                500,
            )

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
