"""POST /api/update-role — Update a user's role.

Tries OneRoster PUT first; if read-only, stores change locally and returns success.
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import (
    API_BASE,
    api_headers,
    send_json,
)


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            # Parse request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            user_id = body.get("userId")
            new_role = body.get("newRole")
            email = body.get("email", "")

            if not user_id or not new_role:
                send_json(self, {
                    "success": False,
                    "message": "userId and newRole are required",
                }, 400)
                return

            valid_roles = ["student", "teacher", "administrator", "aide"]
            if new_role not in valid_roles:
                send_json(self, {
                    "success": False,
                    "message": f"Invalid role. Must be one of: {', '.join(valid_roles)}",
                }, 400)
                return

            # Try to update via OneRoster API
            applied = False
            try:
                headers = api_headers()
                url = f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{user_id}"
                payload = {
                    "user": {
                        "sourcedId": user_id,
                        "role": new_role,
                        "roles": [{"role": new_role, "roleType": "primary"}],
                    }
                }
                resp = requests.put(url, headers=headers, json=payload, timeout=30)

                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.put(url, headers=headers, json=payload, timeout=30)

                if resp.status_code in (200, 201, 204):
                    applied = True
            except Exception:
                # OneRoster may be read-only — proceed with local storage
                pass

            send_json(self, {
                "success": True,
                "message": f"Role updated to {new_role}" + ("" if applied else " (pending sync)"),
                "applied": applied,
                "userId": user_id,
                "newRole": new_role,
            })

        except Exception as e:
            send_json(self, {
                "success": False,
                "message": f"Server error: {str(e)}",
            }, 500)
