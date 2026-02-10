"""GET /api/auth/config — Public configuration for frontend OAuth flow.

Returns the Cognito client ID and domain so the frontend can build
the OAuth redirect URL without hard-coding secrets.
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import CLIENT_ID, send_json

COGNITO_DOMAIN = (
    "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com"
)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        send_json(self, {
            "client_id": CLIENT_ID,
            "cognito_domain": COGNITO_DOMAIN,
        })
