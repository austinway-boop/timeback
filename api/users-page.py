"""GET /api/users-page — Paginated users endpoint (OneRoster)

Query params:
  ?limit=100    — page size (default 100, max 500)
  ?offset=0     — starting offset (default 0)
  ?search=      — filter by name/email substring
  ?role=        — filter by role (student, teacher, administrator, aide)
  ?status=      — filter by status (active, tobedeleted)

Returns a page of users with metadata for pagination.
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import (
    fetch_with_params,
    parse_user,
    send_json,
    get_query_params,
    API_BASE,
    api_headers,
)
import requests


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        try:
            params = get_query_params(self)

            # Parse pagination params
            try:
                limit = min(int(params.get("limit", "100")), 500)
            except (ValueError, TypeError):
                limit = 100
            if limit < 1:
                limit = 100

            try:
                offset = max(int(params.get("offset", "0")), 0)
            except (ValueError, TypeError):
                offset = 0

            search = params.get("search", "").strip()
            role = params.get("role", "").strip()
            status = params.get("status", "").strip()

            # Build OneRoster filter param
            filters = []
            if role:
                filters.append(f"role='{role}'")
            if status:
                filters.append(f"status='{status}'")
            if search:
                # OneRoster 'contains' operator (~)
                # Search across email and name fields
                filters.append(
                    f"email~'{search}' OR givenName~'{search}' OR familyName~'{search}'"
                )

            # Build request params
            api_params = {
                "limit": limit,
                "offset": offset,
            }
            if filters:
                api_params["filter"] = " AND ".join(filters)

            # Fetch from OneRoster with pagination
            url = f"{API_BASE}/ims/oneroster/rostering/v1p2/users"
            headers = api_headers()
            resp = requests.get(url, headers=headers, params=api_params, timeout=60)

            # Retry on 401
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.get(
                    url, headers=headers, params=api_params, timeout=60
                )

            if resp.status_code != 200:
                send_json(
                    self,
                    {
                        "users": [],
                        "count": 0,
                        "total": -1,
                        "offset": offset,
                        "limit": limit,
                        "hasMore": False,
                        "error": f"OneRoster API returned status {resp.status_code}",
                    },
                    502,
                )
                return

            data = resp.json()

            # Extract users from response
            raw_users = data.get("users", [])
            if not raw_users:
                for val in data.values():
                    if isinstance(val, list):
                        raw_users = val
                        break

            users = [parse_user(u) for u in raw_users]

            # Client-side fallback filtering (if OneRoster ignores filters)
            if role and users:
                users = [u for u in users if u["role"] == role]
            if status and users:
                users = [u for u in users if u["status"] == status]
            if search and users:
                s = search.lower()
                users = [
                    u
                    for u in users
                    if s in (u.get("email", "") or "").lower()
                    or s in (u.get("givenName", "") or "").lower()
                    or s in (u.get("familyName", "") or "").lower()
                    or s
                    in f"{u.get('givenName', '')} {u.get('familyName', '')}".lower()
                ]

            # Try to get total count from response header
            total = -1
            total_header = resp.headers.get("X-Total-Count", "")
            if total_header:
                try:
                    total = int(total_header)
                except (ValueError, TypeError):
                    total = -1

            has_more = len(raw_users) >= limit

            send_json(
                self,
                {
                    "users": users,
                    "count": len(users),
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "hasMore": has_more,
                },
            )

        except Exception as e:
            send_json(
                self,
                {
                    "users": [],
                    "count": 0,
                    "total": -1,
                    "offset": 0,
                    "limit": 100,
                    "hasMore": False,
                    "error": str(e),
                },
                500,
            )
