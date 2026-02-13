"""GET /api/users — List all users (OneRoster)"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_all_paginated, parse_user, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            raw_users = fetch_all_paginated(
                "/ims/oneroster/rostering/v1p2/users", "users"
            )
            users = [parse_user(u) for u in raw_users]
            send_json(self, {"users": users, "count": len(users)})
        except Exception as e:
            send_json(self, {"error": str(e), "users": [], "count": 0}, 500)
