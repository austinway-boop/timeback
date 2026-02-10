"""POST /api/auth/login — Email/password login via Timeback OneRoster API.

Looks up the user by email in OneRoster, verifies the password,
and returns the full user profile.
"""

import json
from http.server import BaseHTTPRequestHandler

from api._helpers import (
    fetch_with_params,
    parse_user,
    send_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _lookup_user_by_email(email: str) -> tuple[dict | None, dict | None]:
    """Find a user in OneRoster by email.

    Returns (raw_user_dict, parsed_user_dict) or (None, None).
    """
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
        if users:
            return users[0], parse_user(users[0])
    return None, None


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

            email = data.get("email", "").strip()
            password = data.get("password", "")

            if not email or not password:
                send_json(
                    self,
                    {"error": "Email and password are required", "success": False},
                    400,
                )
                return

            # --- Look up user in Timeback OneRoster ---------------------------
            raw_user, user = _lookup_user_by_email(email)

            if not raw_user:
                send_json(
                    self,
                    {"error": "No account found with that email", "success": False},
                    401,
                )
                return

            # --- Verify password ----------------------------------------------
            stored_password = raw_user.get("password", "")
            if not stored_password or stored_password != password:
                send_json(
                    self,
                    {"error": "Invalid password", "success": False},
                    401,
                )
                return

            send_json(self, {"user": user, "success": True})

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON body", "success": False}, 400)
        except Exception as exc:
            send_json(self, {"error": str(exc), "success": False}, 500)
