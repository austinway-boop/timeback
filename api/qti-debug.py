"""GET /api/qti-debug — Try every possible way to auth with the QTI API.

Tests multiple Cognito configs, scopes, and endpoints to find what works.
"""

import json
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import CLIENT_ID, CLIENT_SECRET, API_BASE, get_token, send_json

# Our Cognito domain
COGNITO_DOMAIN = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com"

# Test item
TEST_ID = "HUMG20-r160029-v1"
TEST_URL = f"{API_BASE}/qti/v3/stimuli/{TEST_ID}"


def try_token(domain, client_id, client_secret, scope=None):
    """Try to get a token and use it."""
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if scope:
        data["scope"] = scope

    try:
        resp = requests.post(
            f"{domain}/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
            timeout=10,
        )
        if resp.status_code != 200:
            return {"token_status": resp.status_code, "token_error": resp.text[:200]}

        token = resp.json().get("access_token", "")
        if not token:
            return {"token_status": 200, "token_error": "No access_token in response"}

        # Try the QTI endpoint with this token
        qti_resp = requests.get(
            TEST_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return {
            "token_status": 200,
            "token_ok": True,
            "qti_status": qti_resp.status_code,
            "qti_ok": qti_resp.status_code == 200,
            "qti_preview": qti_resp.text[:300] if qti_resp.status_code == 200 else qti_resp.text[:200],
        }
    except Exception as e:
        return {"error": str(e)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        results = {}

        # 1. Try our regular token (no scope) on QTI
        results["regular_token"] = {}
        try:
            token = get_token()
            resp = requests.get(TEST_URL, headers={"Authorization": f"Bearer {token}"}, timeout=10)
            results["regular_token"] = {
                "qti_status": resp.status_code,
                "qti_preview": resp.text[:300],
            }
        except Exception as e:
            results["regular_token"] = {"error": str(e)}

        # 2. Try various QTI scopes
        scopes_to_try = [
            "qti/v3/scope/admin",
            "qti/scope/admin",
            "qti/v3/admin",
            "qti/admin",
            "api/qti",
            "qti",
        ]
        for scope in scopes_to_try:
            results[f"scope_{scope}"] = try_token(COGNITO_DOMAIN, CLIENT_ID, CLIENT_SECRET, scope)

        # 3. Try no auth at all
        try:
            resp = requests.get(TEST_URL, timeout=10)
            results["no_auth"] = {"status": resp.status_code, "preview": resp.text[:200]}
        except Exception as e:
            results["no_auth"] = {"error": str(e)}

        # 4. Try the QTI API discovery endpoints
        discovery_urls = [
            f"{API_BASE}/qti/v3",
            f"{API_BASE}/qti",
            f"{API_BASE}/qti/v3/items?limit=1",
            f"{API_BASE}/qti/v3/stimuli?limit=1",
            "https://qti.alpha-1edtech.ai/api",
            "https://qti.alpha-1edtech.ai",
        ]
        try:
            token = get_token()
            for url in discovery_urls:
                try:
                    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=8)
                    results[f"discover_{url.split('/')[-1] or 'root'}"] = {
                        "status": resp.status_code,
                        "preview": resp.text[:200],
                    }
                except Exception as e:
                    results[f"discover_{url.split('/')[-1] or 'root'}"] = {"error": str(e)}
        except Exception:
            pass

        # 5. Show our current credentials (redacted)
        results["config"] = {
            "cognito_domain": COGNITO_DOMAIN,
            "client_id_prefix": CLIENT_ID[:8] + "..." if CLIENT_ID else "MISSING",
            "client_secret_set": bool(CLIENT_SECRET),
            "api_base": API_BASE,
            "test_url": TEST_URL,
        }

        send_json(self, results)
