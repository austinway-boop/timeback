"""GET /api/decrypt-credential?userId=...&credentialId=... — Decrypt a user credential password.

Proxies the decrypt call to the Timeback platform's server function.
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import send_json, get_query_params, get_token

TIMEBACK_DECRYPT_URL = (
    "https://alpha.timeback.com/_serverFn/"
    "src_actions_auth_ts--decryptCredential_createServerFn_handler"
)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        user_id = params.get("userId", "").strip()
        credential_id = params.get("credentialId", "").strip()

        if not user_id or not credential_id:
            send_json(
                self,
                {"error": "Missing userId or credentialId", "success": False},
                400,
            )
            return

        try:
            payload = json.dumps(
                {
                    "data": {
                        "userId": user_id,
                        "credentialId": credential_id,
                    },
                    "context": {},
                }
            )

            req_params = {"payload": payload, "createServerFn": ""}

            # Try with Cognito API token first
            try:
                token = get_token()
                resp = requests.get(
                    TIMEBACK_DECRYPT_URL,
                    params=req_params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    timeout=15,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    send_json(self, {"password": data, "success": True})
                    return
            except Exception:
                pass

            # Fallback: try without auth
            resp2 = requests.get(
                TIMEBACK_DECRYPT_URL,
                params=req_params,
                headers={"Accept": "application/json"},
                timeout=15,
            )

            if resp2.status_code == 200:
                data2 = resp2.json()
                send_json(self, {"password": data2, "success": True})
            else:
                send_json(
                    self,
                    {
                        "error": f"Decrypt failed with status {resp2.status_code}",
                        "success": False,
                        "debug": resp2.text[:500] if resp2.text else "",
                    },
                    502,
                )

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
