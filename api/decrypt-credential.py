"""GET /api/decrypt-credential?userId=...&credentialId=... — Decrypt a user credential password.

Tries multiple approaches:
1. Fetch full user record from OneRoster API and check credential fields
2. Try the Timeback platform decrypt endpoint with API token
3. Try the decrypt endpoint without auth (POST and GET)
4. Return raw credential data and a link to view on Timeback platform
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import send_json, get_query_params, get_token, API_BASE, api_headers

TIMEBACK_DECRYPT_URL = (
    "https://alpha.timeback.com/_serverFn/"
    "src_actions_auth_ts--decryptCredential_createServerFn_handler"
)
TIMEBACK_APP_URL = "https://alpha.timeback.com/app"


def _find_credential_in_user(user_data: dict, credential_id: str) -> tuple:
    """Search user's profiles for the specified credential. Returns (password, raw_cred)."""
    raw_user = user_data.get("user", user_data)
    profiles = raw_user.get("userProfiles", [])

    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        for cred in profile.get("credentials", []):
            if not isinstance(cred, dict):
                continue
            if cred.get("id") == credential_id:
                password = (
                    cred.get("password", "")
                    or cred.get("pass", "")
                    or cred.get("secret", "")
                    or cred.get("passphrase", "")
                    or cred.get("value", "")
                    or cred.get("credential", "")
                    or ""
                )
                return password, cred

    return "", None


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
            # ── Approach 1: Check OneRoster API for password fields ──
            try:
                headers = api_headers()
                resp = requests.get(
                    f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{user_id}",
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.get(
                        f"{API_BASE}/ims/oneroster/rostering/v1p2/users/{user_id}",
                        headers=headers,
                        timeout=30,
                    )

                if resp.status_code == 200:
                    user_data = resp.json()
                    password, raw_cred = _find_credential_in_user(
                        user_data, credential_id
                    )
                    if password:
                        send_json(
                            self,
                            {
                                "password": password,
                                "success": True,
                                "source": "oneroster",
                            },
                        )
                        return

                    # Found the credential but no password field
                    if raw_cred:
                        # Return the raw credential fields and a Timeback link
                        username = raw_cred.get("username", "")
                        send_json(
                            self,
                            {
                                "success": False,
                                "username": username,
                                "credentialType": raw_cred.get("type", ""),
                                "rawFields": raw_cred,
                                "viewUrl": TIMEBACK_APP_URL,
                                "message": "Password available on Timeback platform",
                            },
                        )
                        return
            except Exception:
                pass

            # ── Approach 2: Try Timeback decrypt endpoint with Bearer token ──
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
                token = get_token()

                # Try GET with auth
                resp = requests.get(
                    TIMEBACK_DECRYPT_URL,
                    params={"payload": payload, "createServerFn": ""},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    send_json(
                        self,
                        {"password": data, "success": True, "source": "decrypt_get"},
                    )
                    return

                # Try POST with auth
                resp2 = requests.post(
                    TIMEBACK_DECRYPT_URL,
                    json={
                        "data": {
                            "userId": user_id,
                            "credentialId": credential_id,
                        },
                        "context": {},
                    },
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=15,
                )
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    send_json(
                        self,
                        {
                            "password": data2,
                            "success": True,
                            "source": "decrypt_post",
                        },
                    )
                    return
            except Exception:
                pass

            # ── Approach 3: Try without auth ──
            try:
                resp3 = requests.get(
                    TIMEBACK_DECRYPT_URL,
                    params={"payload": payload, "createServerFn": ""},
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
                if resp3.status_code == 200:
                    data3 = resp3.json()
                    send_json(
                        self,
                        {
                            "password": data3,
                            "success": True,
                            "source": "decrypt_noauth",
                        },
                    )
                    return
            except Exception:
                pass

            # ── Fallback: Return useful info with Timeback link ──
            send_json(
                self,
                {
                    "success": False,
                    "viewUrl": TIMEBACK_APP_URL,
                    "message": "Password available on Timeback platform",
                },
            )

        except Exception as e:
            send_json(
                self,
                {
                    "error": str(e),
                    "success": False,
                    "viewUrl": TIMEBACK_APP_URL,
                    "message": "Password available on Timeback platform",
                },
                500,
            )
