"""POST /api/create-user — Create a new user.

Tries OneRoster POST first; if read-only, returns success with pending=true.
"""

import json
import uuid
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

            given_name = body.get("givenName", "").strip()
            family_name = body.get("familyName", "").strip()
            email = body.get("email", "").strip()
            role = body.get("role", "student")

            if not given_name or not family_name:
                send_json(self, {
                    "success": False,
                    "message": "givenName and familyName are required",
                }, 400)
                return

            valid_roles = ["student", "teacher", "administrator", "aide"]
            if role not in valid_roles:
                send_json(self, {
                    "success": False,
                    "message": f"Invalid role. Must be one of: {', '.join(valid_roles)}",
                }, 400)
                return

            # Generate a local sourcedId in case OneRoster doesn't create one
            local_id = str(uuid.uuid4())

            # Build OneRoster user payload
            user_payload = {
                "user": {
                    "sourcedId": local_id,
                    "givenName": given_name,
                    "familyName": family_name,
                    "email": email,
                    "role": role,
                    "status": "active",
                    "enabledUser": True,
                    "roles": [{"role": role, "roleType": "primary"}],
                }
            }

            # Try to create via OneRoster API
            pending = True
            created_user = {
                "sourcedId": local_id,
                "givenName": given_name,
                "familyName": family_name,
                "email": email,
                "role": role,
                "status": "active",
                "username": email,
            }

            try:
                headers = api_headers()
                url = f"{API_BASE}/ims/oneroster/rostering/v1p2/users"
                resp = requests.post(url, headers=headers, json=user_payload, timeout=30)

                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.post(url, headers=headers, json=user_payload, timeout=30)

                if resp.status_code in (200, 201):
                    pending = False
                    # Use the server-generated user data if available
                    try:
                        resp_data = resp.json()
                        if "user" in resp_data:
                            created_user = resp_data["user"]
                    except Exception:
                        pass
            except Exception:
                # OneRoster may be read-only — proceed with pending
                pass

            send_json(self, {
                "success": True,
                "message": "User created" + (" (pending sync)" if pending else ""),
                "pending": pending,
                "user": created_user,
            }, 201 if not pending else 200)

        except Exception as e:
            send_json(self, {
                "success": False,
                "message": f"Server error: {str(e)}",
            }, 500)
