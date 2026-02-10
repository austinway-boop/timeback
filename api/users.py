"""Vercel serverless function – GET /api/users"""

import json
import os
from http.server import BaseHTTPRequestHandler

import requests

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
CLIENT_ID = os.environ.get("TIMEBACK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TIMEBACK_CLIENT_SECRET", "")
ONEROSTER_BASE = "https://api.alpha-1edtech.ai"
PAGE_SIZE = 3000


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
        url = f"{ONEROSTER_BASE}/ims/oneroster/rostering/v1p2/users"
        all_users = []
        offset = 0
        headers = _api_headers()

        while True:
            params = {"limit": PAGE_SIZE, "offset": offset}
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=120)
                if resp.status_code == 401:
                    headers = _api_headers()
                    resp = requests.get(url, headers=headers, params=params, timeout=120)
                if resp.status_code != 200:
                    break

                data = resp.json()
                page_items = []
                for key in data:
                    if isinstance(data[key], list):
                        page_items = data[key]
                        break
                if not page_items:
                    break
                all_users.extend(page_items)
                if len(page_items) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
            except Exception:
                break

        users = [_parse_user(u) for u in all_users]
        body = json.dumps({"users": users, "count": len(users)})

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())
