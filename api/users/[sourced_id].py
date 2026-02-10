"""Vercel serverless function – GET /api/users/:sourced_id"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler

import requests

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
CLIENT_ID = os.environ.get("TIMEBACK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TIMEBACK_CLIENT_SECRET", "")
ONEROSTER_BASE = "https://api.alpha-1edtech.ai"


def _get_token() -> str:
    resp = requests.post(
        COGNITO_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _api_headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


def _parse_user(raw: dict) -> dict:
    role = raw.get("role", "")
    if not role:
        roles = raw.get("roles", [])
        if isinstance(roles, list) and roles:
            first = roles[0]
            role = first.get("role", "") if isinstance(first, dict) else str(first)
    return {
        "sourcedId": raw.get("sourcedId", ""),
        "givenName": raw.get("givenName", ""),
        "familyName": raw.get("familyName", ""),
        "email": raw.get("email", ""),
        "role": role,
        "status": raw.get("status", ""),
        "username": raw.get("username", ""),
        "roles": raw.get("roles", []),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Extract sourced_id from the URL path  /api/users/<sourced_id>
        match = re.search(r"/api/users/([^/]+)", self.path)
        if not match:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing user ID"}).encode())
            return

        sourced_id = match.group(1)
        url = f"{ONEROSTER_BASE}/ims/oneroster/rostering/v1p2/users/{sourced_id}"

        try:
            headers = _api_headers()
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 401:
                headers = _api_headers()
                resp = requests.get(url, headers=headers, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                user = data.get("user", data)
                body = json.dumps({"user": _parse_user(user)})
            else:
                body = json.dumps({"error": f"HTTP {resp.status_code}"})

            self.send_response(resp.status_code if resp.status_code == 200 else resp.status_code)
        except Exception as e:
            body = json.dumps({"error": str(e)})
            self.send_response(500)

        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())
