"""POST /api/auth/signup — Create a new user via Timeback OneRoster API.

Creates a user record in OneRoster with the provided name, email,
and password.  Checks for duplicates before creating.
"""

import json
import uuid
from http.server import BaseHTTPRequestHandler

from api._helpers import (
    fetch_with_params,
    post_resource,
    send_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user_exists(email: str) -> bool:
    """Return True if a user with this email already exists in OneRoster."""
    data, status = fetch_with_params(
        "/ims/oneroster/rostering/v1p2/users",
        {"filter": f"email='{email}'"},
    )
    if data and status == 200:
        users = data.get("users", [])
        if not users:
            for val in data.values():
                if isinstance(val, list) and val:
                    users = val
                    break
        return len(users) > 0
    return False


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        self.end_headers()

    def do_GET(self):
        send_json(self, {"error": "Method not allowed. Use POST.", "success": False}, 405)

    def do_POST(self):
        try:
            # --- Parse body ---------------------------------------------------
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            data = json.loads(raw_body)

            given_name = data.get("givenName", "").strip()
            family_name = data.get("familyName", "").strip()
            email = data.get("email", "").strip()
            password = data.get("password", "")

            if not email or not password:
                send_json(
                    self,
                    {"error": "Email and password are required", "success": False},
                    400,
                )
                return

            if not given_name or not family_name:
                send_json(
                    self,
                    {"error": "First name and last name are required", "success": False},
                    400,
                )
                return

            # --- Check for existing user --------------------------------------
            if _user_exists(email):
                send_json(
                    self,
                    {"error": "An account with this email already exists", "success": False},
                    400,
                )
                return

            # --- Create user via OneRoster ------------------------------------
            user_id = str(uuid.uuid4())
            user_payload = {
                "user": {
                    "sourcedId": user_id,
                    "status": "active",
                    "enabledUser": "true",
                    "givenName": given_name,
                    "familyName": family_name,
                    "email": email,
                    "username": email,
                    "password": password,
                    "roles": [
                        {"role": "student", "roleType": "primary"},
                    ],
                }
            }

            resp_data, status = post_resource(
                "/ims/oneroster/rostering/v1p2/users",
                user_payload,
            )

            if status not in (200, 201):
                error_msg = "Failed to create account"
                if resp_data and isinstance(resp_data, dict):
                    # Try common error response shapes
                    error_msg = (
                        resp_data.get("message")
                        or resp_data.get("error")
                        or resp_data.get("statusInfoSet", [{}])[0].get("imsx_description", error_msg)
                    )
                send_json(self, {"error": error_msg, "success": False}, 400)
                return

            send_json(self, {"message": "Account created successfully", "success": True})

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON body", "success": False}, 400)
        except Exception as exc:
            send_json(self, {"error": str(exc), "success": False}, 500)
