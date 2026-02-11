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

        if not item_id:
            send_json(self, {"error": "Missing id parameter"}, 400)
            return

        try:
            token = _get_token()
            headers = {"Authorization": f"Bearer {token}"}

            # Map type to API path segment
            path_segment = TYPE_MAP.get(item_type, "items")

            # Primary path: /qti/v3/{type}/{id}
            url = f"{QTI_API}/qti/v3/{path_segment}/{item_id}"
            resp = requests.get(url, headers=headers, timeout=30)

            if resp.status_code == 200:
                send_json(self, {"data": resp.json(), "success": True})
                return

            # If primary fails, try alternate paths
            alternates = [
                f"{QTI_API}/ims/qti3p0/{path_segment}/{item_id}",
                f"{QTI_API}/qti/v3/items/{item_id}",
            ]
            for alt_url in alternates:
                try:
                    alt_resp = requests.get(alt_url, headers=headers, timeout=15)
                    if alt_resp.status_code == 200:
                        send_json(self, {"data": alt_resp.json(), "success": True})
                        return
                except Exception:
                    continue

            send_json(self, {
                "error": f"QTI API returned {resp.status_code}",
                "success": False,
                "url": url,
                "detail": resp.text[:300],
            }, resp.status_code)

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
