"""GET /api/users/:sourced_id — Single user detail (OneRoster)"""

import re
from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_one, parse_user, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        match = re.search(r"/api/users/([^/?]+)", self.path)
        if not match:
            send_json(self, {"error": "Missing user ID"}, 400)
            return

        sourced_id = match.group(1)
        try:
            data, status = fetch_one(
                f"/ims/oneroster/rostering/v1p2/users/{sourced_id}"
            )
            if data:
                user = data.get("user", data)
                send_json(self, {"user": parse_user(user)})
            else:
                send_json(self, {"error": f"HTTP {status}"}, status)
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
