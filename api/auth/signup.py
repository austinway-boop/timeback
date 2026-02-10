"""POST /api/auth/signup — Create a new account via Cognito User Pool."""

import json
import hmac
import hashlib
import base64
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import CLIENT_ID, CLIENT_SECRET, send_json

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

            # --- Cognito SignUp -----------------------------------------------
            secret_hash = _compute_secret_hash(email)

            cognito_resp = requests.post(
                COGNITO_IDP_URL,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "AWSCognitoIdentityProviderService.SignUp",
                },
                json={
                    "ClientId": CLIENT_ID,
                    "Username": email,
                    "Password": password,
                    "SecretHash": secret_hash,
                    "UserAttributes": [
                        {"Name": "email", "Value": email},
                        {"Name": "given_name", "Value": given_name},
                        {"Name": "family_name", "Value": family_name},
                    ],
                },
                timeout=30,
            )

            if cognito_resp.status_code != 200:
                err = cognito_resp.json()
                send_json(
                    self,
                    {"error": err.get("message", "Signup failed"), "success": False},
                    400,
                )
                return

            send_json(self, {"message": "Account created successfully", "success": True})

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON body", "success": False}, 400)
        except Exception as exc:
            send_json(self, {"error": str(exc), "success": False}, 500)
