"""GET /api/qti-item?id=...&type=stimulus|item|assessment OR ?url=...

Fetch QTI content from https://api.alpha-1edtech.ai/qti/v3/{type}/{id}
Auth: Cognito token with qti/v3/scope/admin scope.
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import CLIENT_ID, CLIENT_SECRET, send_json, get_query_params

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://api.alpha-1edtech.ai"

TYPE_MAP = {
    "stimulus": "stimuli",
    "stimuli": "stimuli",
    "item": "items",
    "items": "items",
    "assessment": "assessments",
    "assessments": "assessments",
}


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        item_id = params.get("id", "").strip()
        item_type = params.get("type", "items").strip().lower()
        direct_url = params.get("url", "").strip()

        if not item_id and not direct_url:
            send_json(self, {"error": "Need id or url param"}, 400)
            return

        # Step 1: Get Cognito token with QTI scope
        token = None
        token_error = None
        try:
            resp = requests.post(
                COGNITO_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "scope": "qti/v3/scope/admin",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                token = resp.json().get("access_token")
            else:
                token_error = f"Cognito returned {resp.status_code}: {resp.text[:200]}"
                # Fallback: try without scope
                resp2 = requests.post(
                    COGNITO_URL,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "client_credentials",
                        "client_id": CLIENT_ID,
                        "client_secret": CLIENT_SECRET,
                    },
                    timeout=15,
                )
                if resp2.status_code == 200:
                    token = resp2.json().get("access_token")
                    token_error += " (using fallback token without QTI scope)"
        except Exception as e:
            token_error = f"Token error: {str(e)}"

        if not token:
            send_json(self, {
                "error": "Could not get auth token",
                "detail": token_error,
                "success": False,
            }, 500)
            return

        headers = {"Authorization": f"Bearer {token}"}

        # Step 2: Fetch QTI content
        try:
            # If direct URL provided, use it
            if direct_url:
                resp = requests.get(direct_url, headers=headers, timeout=30)
                if resp.status_code == 200:
                    send_json(self, {"data": resp.json(), "success": True})
                    return
                send_json(self, {
                    "error": f"QTI returned {resp.status_code}",
                    "url": direct_url,
                    "detail": resp.text[:500],
                    "token_note": token_error or "Token OK",
                    "success": False,
                }, resp.status_code)
                return

            # Build URL from id + type
            path_segment = TYPE_MAP.get(item_type, "items")
            url = f"{QTI_BASE}/qti/v3/{path_segment}/{item_id}"

            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                send_json(self, {"data": resp.json(), "success": True})
                return

            # Try other type paths
            tried = [f"{url}: {resp.status_code}"]
            for alt_type in ["stimuli", "items", "assessments"]:
                if alt_type == path_segment:
                    continue
                alt_url = f"{QTI_BASE}/qti/v3/{alt_type}/{item_id}"
                alt_resp = requests.get(alt_url, headers=headers, timeout=15)
                if alt_resp.status_code == 200:
                    send_json(self, {"data": alt_resp.json(), "success": True})
                    return
                tried.append(f"{alt_url}: {alt_resp.status_code}")

            send_json(self, {
                "error": "QTI item not found",
                "tried": tried,
                "token_note": token_error or "Token OK with QTI scope",
                "success": False,
            }, 404)

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
