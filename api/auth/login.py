"""POST /api/auth/login — Email/password login via Cognito User Pool.

Authenticates using USER_PASSWORD_AUTH flow, then looks up the user
in OneRoster to return a full profile.
"""

import json
import hmac
import hashlib
import base64
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import (
    CLIENT_ID,
    CLIENT_SECRET,
    fetch_with_params,
    parse_user,
    send_json,
)

COGNITO_IDP_URL = "https://cognito-idp.us-east-1.amazonaws.com/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_secret_hash(username: str) -> str:
    """Compute the Cognito SECRET_HASH for *username*."""
    message = username + CLIENT_ID
    dig = hmac.new(
        CLIENT_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(dig).decode("utf-8")


def _decode_jwt_payload(token: str) -> dict:
    """Decode a JWT payload **without** signature verification.

    Safe here because we just received the token from Cognito directly.
    """
    payload_b64 = token.split(".")[1]
    # JWT base64url may lack padding
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def _lookup_user_by_email(email: str) -> dict | None:
    """Try to find a user in OneRoster by email address."""
    data, status = fetch_with_params(
        "/ims/oneroster/rostering/v1p2/users",
        {"filter": f"email='{email}'"},
    )
    if data and status == 200:
        users = data.get("users", [])
        if not users:
            # Some OneRoster implementations wrap the list under a different key
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

            # --- Cognito InitiateAuth -----------------------------------------
            secret_hash = _compute_secret_hash(email)

            cognito_resp = requests.post(
                COGNITO_IDP_URL,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
                },
                json={
                    "AuthFlow": "USER_PASSWORD_AUTH",
                    "ClientId": CLIENT_ID,
                    "AuthParameters": {
                        "USERNAME": email,
                        "PASSWORD": password,
                        "SECRET_HASH": secret_hash,
                    },
                },
                timeout=30,
            )

            if cognito_resp.status_code != 200:
                err = cognito_resp.json()
                send_json(
                    self,
                    {
                        "error": err.get("message", "Invalid credentials"),
                        "success": False,
                    },
                    401,
                )
                return

            auth_result = cognito_resp.json().get("AuthenticationResult", {})
            id_token = auth_result.get("IdToken", "")

            if not id_token:
                send_json(
                    self,
                    {"error": "Authentication failed — no token received", "success": False},
                    401,
                )
                return

            # --- Resolve user profile -----------------------------------------
            token_payload = _decode_jwt_payload(id_token)
            user_email = token_payload.get("email", email)

            user = _lookup_user_by_email(user_email)
            if not user:
                # Build a minimal profile from the Cognito token claims
                user = {
                    "sourcedId": token_payload.get("sub", ""),
                    "givenName": token_payload.get("given_name", ""),
                    "familyName": token_payload.get("family_name", ""),
                    "email": user_email,
                    "role": "",
                    "status": "active",
                }

            send_json(self, {"user": user, "success": True})

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON body", "success": False}, 400)
        except Exception as exc:
            send_json(self, {"error": str(exc), "success": False}, 500)
