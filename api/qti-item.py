"""GET /api/qti-item?id=... — Fetch a QTI quiz/assessment item from the QTI API.

Gets a Cognito token with qti/v3/scope/admin scope, then fetches the item.
"""

import os
from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import CLIENT_ID, CLIENT_SECRET, send_json, get_query_params

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://api.alpha-1edtech.ai"


def _get_qti_token():
    """Get a Cognito token with QTI scope."""
    resp = requests.post(
        COGNITO_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "qti/v3/scope/admin",
        },
        timeout=30,
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
        item_type = params.get("type", "item").strip()  # "item", "assessment", "stimulus"

        if not item_id:
            send_json(self, {"error": "Need id param"}, 400)
            return

        try:
            token = _get_qti_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            # Try multiple QTI API paths
            paths = []
            if item_type == "assessment":
                paths = [
                    f"/qti/v3/assessments/{item_id}",
                    f"/ims/qti3p0/assessments/{item_id}",
                ]
            elif item_type == "stimulus":
                paths = [
                    f"/qti/v3/stimuli/{item_id}",
                    f"/ims/qti3p0/stimuli/{item_id}",
                ]
            else:
                paths = [
                    f"/qti/v3/items/{item_id}",
                    f"/ims/qti3p0/items/{item_id}",
                    f"/qti/v3/assessments/{item_id}",
                ]

            for path in paths:
                try:
                    resp = requests.get(
                        f"{QTI_BASE}{path}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        send_json(self, {"data": data, "success": True, "path": path})
                        return
                except Exception:
                    continue

            # If none worked, return the last error
            send_json(self, {
                "error": f"QTI item not found (tried {len(paths)} paths)",
                "success": False,
            }, 404)

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
