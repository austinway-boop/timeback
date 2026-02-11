"""GET /api/user-credentials?email=... or ?userId=...

Fetches the FULL user record from OneRoster and extracts ALL credential data
from userProfiles, including raw credential objects for debugging.

Returns a list of app profiles with whatever credential fields exist.
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import (
    fetch_with_params,
    send_json,
    get_query_params,
    API_BASE,
    api_headers,
)
import requests


def _extract_profiles(raw_user: dict) -> list:
    """Extract credential profiles from a raw OneRoster user record."""
    profiles_list = raw_user.get("userProfiles", [])
    if not isinstance(profiles_list, list):
        profiles_list = []

    result = []
    for p in profiles_list:
        if not isinstance(p, dict):
            continue

        vendor_id = p.get("vendorId", "") or p.get("applicationId", "")
        if not vendor_id:
            continue

        app = p.get("app", {}) or {}
        app_domains = app.get("domain", []) or []
        creds_list = p.get("credentials", []) or []

        # Extract ALL fields from the first credential object
        first_cred = creds_list[0] if creds_list else {}
        username = ""
        password = ""
        cred_type = ""

        if isinstance(first_cred, dict):
            cred_type = first_cred.get("type", "")
            username = (
                first_cred.get("username", "")
                or first_cred.get("user", "")
                or first_cred.get("login", "")
                or first_cred.get("email", "")
                or ""
            )
            password = (
                first_cred.get("password", "")
                or first_cred.get("pass", "")
                or first_cred.get("secret", "")
                or first_cred.get("passphrase", "")
                or first_cred.get("credential", "")
                or ""
            )

        domain = app_domains[0] if app_domains else ""
        launch_url = f"https://{domain}" if domain else ""

        profile = {
            "vendorId": vendor_id,
            "appName": app.get("name", "") or p.get("description", ""),
            "domain": domain,
            "launchUrl": launch_url,
            "username": username,
            "password": password,
            "credentialType": cred_type,
            "rawCredentials": creds_list,
        }
        result.append(profile)

    return result


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        try:
            params = get_query_params(self)
            email = params.get("email", "").strip()
            user_id = params.get("userId", "").strip()

            if not email and not user_id:
                send_json(
                    self,
                    {"error": "Provide 'email' or 'userId' query param", "profiles": []},
                    400,
                )
                return

            raw_user = None

            if email:
                # Fetch by email filter
                data, status = fetch_with_params(
                    "/ims/oneroster/rostering/v1p2/users",
                    {"filter": f"email='{email}'", "limit": 1},
                )
                if data:
                    users_list = data.get("users", [])
                    if not users_list:
                        for val in data.values():
                            if isinstance(val, list) and val:
                                users_list = val
                                break
                    if users_list:
                        raw_user = users_list[0]

            elif user_id:
                # Fetch by direct ID
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
                    data = resp.json()
                    raw_user = data.get("user", data)

            if not raw_user:
                send_json(
                    self,
                    {"error": "User not found", "profiles": []},
                    404,
                )
                return

            profiles = _extract_profiles(raw_user)

            send_json(
                self,
                {
                    "profiles": profiles,
                    "count": len(profiles),
                    "userId": raw_user.get("sourcedId", ""),
                },
            )

        except Exception as e:
            send_json(
                self,
                {"error": str(e), "profiles": []},
                500,
            )
