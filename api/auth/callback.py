"""GET /api/auth/callback — Exchange OAuth authorization code for tokens.

Used after Google Sign-In redirects back from Cognito Hosted UI.
Exchanges the code for tokens, fetches Cognito userInfo, then looks
up the user in OneRoster to return a full profile.
"""

from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import (
    CLIENT_ID,
    CLIENT_SECRET,
    fetch_with_params,
    parse_user,
    send_json,
    get_query_params,
)

COGNITO_DOMAIN = (
    "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _lookup_user_by_email(email: str) -> dict | None:
    """Try to find a user in OneRoster by email address."""
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
            return parse_user(users[0])
    return None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        self.end_headers()

    def do_GET(self):
        try:
            params = get_query_params(self)
            code = params.get("code", "")
            redirect_uri = params.get("redirect_uri", "")

            if not code:
                send_json(
                    self,
                    {"error": "Missing 'code' query parameter", "success": False},
                    400,
                )
                return

            if not redirect_uri:
                send_json(
                    self,
                    {"error": "Missing 'redirect_uri' query parameter", "success": False},
                    400,
                )
                return

            # --- Exchange code for tokens -------------------------------------
            token_resp = requests.post(
                f"{COGNITO_DOMAIN}/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
                timeout=30,
            )

            if token_resp.status_code != 200:
                err = token_resp.json()
                msg = err.get(
                    "error_description", err.get("error", "Token exchange failed")
                )
                send_json(self, {"error": msg, "success": False}, 400)
                return

            tokens = token_resp.json()
            access_token = tokens.get("access_token", "")

            if not access_token:
                send_json(
                    self,
                    {"error": "No access token received", "success": False},
                    400,
                )
                return

            # --- Fetch user info from Cognito ---------------------------------
            userinfo_resp = requests.get(
                f"{COGNITO_DOMAIN}/oauth2/userInfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )

            if userinfo_resp.status_code != 200:
                send_json(
                    self,
                    {"error": "Failed to retrieve user info from Cognito", "success": False},
                    400,
                )
                return

            userinfo = userinfo_resp.json()
            user_email = userinfo.get("email", "")

            if not user_email:
                send_json(
                    self,
                    {"error": "No email address in Cognito user info", "success": False},
                    400,
                )
                return

            # --- Resolve OneRoster profile ------------------------------------
            user = _lookup_user_by_email(user_email)
            if not user:
                # Build a minimal profile from Cognito userInfo
                user = {
                    "sourcedId": userinfo.get("sub", ""),
                    "givenName": userinfo.get("given_name", ""),
                    "familyName": userinfo.get("family_name", ""),
                    "email": user_email,
                    "role": "",
                    "status": "active",
                }

            send_json(self, {"user": user, "success": True})

        except Exception as exc:
            send_json(self, {"error": str(exc), "success": False}, 500)
