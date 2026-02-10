"""
Shared helpers for Timeback API serverless functions.

Auth: OAuth 2.0 client credentials → Cognito
API base: https://api.alpha-1edtech.ai

Docs: https://docs.timeback.com/beta/api-reference/overview
"""

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
CLIENT_ID = os.environ.get("TIMEBACK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TIMEBACK_CLIENT_SECRET", "")
API_BASE = "https://api.alpha-1edtech.ai"
PAGE_SIZE = 3000


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_token() -> str:
    """Exchange client credentials for a Cognito access token."""
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


def api_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def fetch_all_paginated(path: str, collection_key: str | None = None) -> list:
    """
    Fetch all records from a paginated OneRoster endpoint.
    Handles 3000-per-page batches and auto-retries on 401.
    """
    url = f"{API_BASE}{path}"
    all_items = []
    offset = 0
    headers = api_headers()

    while True:
        params = {"limit": PAGE_SIZE, "offset": offset}
        resp = requests.get(url, headers=headers, params=params, timeout=120)

        if resp.status_code == 401:
            headers = api_headers()
            resp = requests.get(url, headers=headers, params=params, timeout=120)

        if resp.status_code != 200:
            break

        data = resp.json()

        # OneRoster wraps lists in a named key (e.g. "users", "courses")
        page_items = []
        if collection_key and collection_key in data:
            page_items = data[collection_key]
        else:
            for key in data:
                if isinstance(data[key], list):
                    page_items = data[key]
                    break

        if not page_items:
            break

        all_items.extend(page_items)

        if len(page_items) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return all_items


def fetch_one(path: str) -> tuple[dict | None, int]:
    """Fetch a single resource. Returns (data, status_code)."""
    url = f"{API_BASE}{path}"
    headers = api_headers()
    resp = requests.get(url, headers=headers, timeout=30)

    if resp.status_code == 401:
        headers = api_headers()
        resp = requests.get(url, headers=headers, timeout=30)

    if resp.status_code == 200:
        return resp.json(), 200
    return None, resp.status_code


def fetch_with_params(path: str, params: dict) -> tuple[dict | None, int]:
    """Fetch a resource with query params. Returns (data, status_code)."""
    url = f"{API_BASE}{path}"
    headers = api_headers()
    resp = requests.get(url, headers=headers, params=params, timeout=60)

    if resp.status_code == 401:
        headers = api_headers()
        resp = requests.get(url, headers=headers, params=params, timeout=60)

    if resp.status_code == 200:
        return resp.json(), 200
    return None, resp.status_code


def post_resource(path: str, payload: dict) -> tuple[dict | None, int]:
    """POST a new resource. Returns (response_data, status_code)."""
    url = f"{API_BASE}{path}"
    headers = api_headers()
    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    if resp.status_code == 401:
        headers = api_headers()
        resp = requests.post(url, headers=headers, json=payload, timeout=30)

    try:
        return resp.json(), resp.status_code
    except Exception:
        return None, resp.status_code


# ---------------------------------------------------------------------------
# User parser
# ---------------------------------------------------------------------------
def parse_user(raw: dict) -> dict:
    """Normalise a OneRoster user record into a clean dict."""
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


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def send_json(handler: BaseHTTPRequestHandler, data: dict, status: int = 200):
    """Send a JSON response with CORS headers."""
    body = json.dumps(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body.encode())


def get_query_params(handler: BaseHTTPRequestHandler) -> dict:
    """Parse query string params from the request URL."""
    parsed = urlparse(handler.path)
    return {k: v[0] for k, v in parse_qs(parsed.query).items()}
