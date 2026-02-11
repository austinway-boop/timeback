"""GET /api/qti-item?id=...&type=item|assessment|stimulus

Fetch a QTI quiz/assessment/stimulus from the QTI API.
Tries multiple auth approaches and API paths.
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import CLIENT_ID, CLIENT_SECRET, API_BASE, api_headers, get_token, send_json, get_query_params

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"


def _get_qti_token():
    """Try to get a Cognito token with QTI scope. Falls back to regular token."""
    # Try with QTI scope
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
            return resp.json()["access_token"]
    except Exception:
        pass

    # Fall back to regular token (no scope)
    return get_token()


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
        item_type = params.get("type", "item").strip()

        if not item_id:
            send_json(self, {"error": "Need id param"}, 400)
            return

        try:
            token = _get_qti_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

            # Build paths to try based on type
            paths = []
            if item_type == "stimulus":
                paths = [
                    f"/qti/v3/stimuli/{item_id}",
                    f"/api/stimuli/{item_id}",
                    f"/qti/v3/items/{item_id}",
                ]
            elif item_type == "assessment":
                paths = [
                    f"/qti/v3/assessments/{item_id}",
                    f"/api/assessments/{item_id}",
                    f"/qti/v3/items/{item_id}",
                ]
            else:
                paths = [
                    f"/qti/v3/items/{item_id}",
                    f"/api/items/{item_id}",
                    f"/qti/v3/assessments/{item_id}",
                    f"/qti/v3/stimuli/{item_id}",
                ]

            # Also try the paths the resources reference directly
            # e.g. https://qti.alpha-1edtech.ai/api/stimuli/...
            qti_paths = [
                f"/api/stimuli/{item_id}",
                f"/api/assessment-items/{item_id}",
                f"/api/assessments/{item_id}",
                f"/api/items/{item_id}",
            ]
            paths.extend(qti_paths)

            errors = []
            for path in paths:
                try:
                    # Try on the main API
                    resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=15)
                    if resp.status_code == 200:
                        send_json(self, {"data": resp.json(), "success": True, "path": path})
                        return
                    errors.append(f"{path}: {resp.status_code}")

                    # Also try on the QTI-specific domain
                    resp2 = requests.get(f"https://qti.alpha-1edtech.ai{path}", headers=headers, timeout=15)
                    if resp2.status_code == 200:
                        send_json(self, {"data": resp2.json(), "success": True, "path": f"qti.alpha-1edtech.ai{path}"})
                        return
                    errors.append(f"qti:{path}: {resp2.status_code}")
                except Exception as e:
                    errors.append(f"{path}: {str(e)}")

            send_json(self, {
                "error": "QTI item not found",
                "success": False,
                "tried": errors[:10],
            }, 404)

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
