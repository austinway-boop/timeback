"""GET /api/qti-item?id=...&type=stimulus|item|assessment

Fetch a QTI item from https://api.alpha-1edtech.ai/qti/v3/{type}/{id}
Uses Cognito token with qti/v3/scope/admin scope.
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import CLIENT_ID, CLIENT_SECRET, send_json, get_query_params

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_API = "https://api.alpha-1edtech.ai"

# Map type param to QTI API path segment
TYPE_MAP = {
    "stimulus": "stimuli",
    "stimuli": "stimuli",
    "item": "items",
    "items": "items",
    "assessment": "assessments",
    "assessments": "assessments",
    "assessment-item": "assessment-items",
}


def _get_token():
    """Get Cognito token with QTI scope."""
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
    if resp.status_code != 200:
        # Fallback: try without scope
        resp = requests.post(
            COGNITO_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            timeout=15,
        )
    resp.raise_for_status()
    return resp.json()["access_token"]


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
        direct_url = params.get("url", "").strip()  # The actual QTI URL from resource metadata

        if not item_id and not direct_url:
            send_json(self, {"error": "Need id or url param"}, 400)
            return

        try:
            token = _get_token()
            headers = {"Authorization": f"Bearer {token}"}

            # If we have the direct URL from the resource metadata, use it
            if direct_url:
                resp = requests.get(direct_url, headers=headers, timeout=30)
                if resp.status_code == 200:
                    send_json(self, {"data": resp.json(), "success": True})
                    return
                # Try adding auth as query param
                resp2 = requests.get(direct_url, headers=headers, timeout=30)
                send_json(self, {
                    "error": f"QTI API returned {resp.status_code}",
                    "success": False,
                    "url": direct_url,
                    "detail": resp.text[:500],
                }, resp.status_code)
                return

            # Otherwise try constructing the path from id + type
            path_segment = TYPE_MAP.get(item_type, "items")
            urls_to_try = [
                f"{QTI_API}/qti/v3/{path_segment}/{item_id}",
                f"https://qti.alpha-1edtech.ai/api/{path_segment}/{item_id}",
                f"{QTI_API}/qti/v3/items/{item_id}",
                f"https://qti.alpha-1edtech.ai/api/items/{item_id}",
            ]

            for url in urls_to_try:
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                    if resp.status_code == 200:
                        send_json(self, {"data": resp.json(), "success": True})
                        return
                except Exception:
                    continue

            send_json(self, {
                "error": "QTI item not found",
                "success": False,
            }, 404)

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
