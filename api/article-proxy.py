"""
Proxy for fetching article/stimuli content from PowerPath.
These URLs require Cognito auth that the browser doesn't have.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests
import json

from _helpers import get_token, API_BASE


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        url = (query.get("url") or [None])[0]

        if not url:
            self._json(400, {"error": "Missing 'url' parameter"})
            return

        try:
            headers = {
                "Authorization": f"Bearer {get_token()}",
                "Accept": "text/html, application/json, */*",
            }
            resp = requests.get(url, headers=headers, timeout=30)

            content_type = resp.headers.get("Content-Type", "")

            # If JSON response, extract body/content field
            if "application/json" in content_type:
                data = resp.json()
                # PowerPath stimuli may return JSON with a body/content field
                body = data.get("body") or data.get("content") or data.get("html") or data.get("text") or ""
                if not body and isinstance(data, dict):
                    # Try to render the whole thing as formatted text
                    body = "<pre>" + json.dumps(data, indent=2) + "</pre>"
                self._html(200, body)
            else:
                # Return HTML content directly
                self._html(200, resp.text)

        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, status, html):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html.encode() if isinstance(html, str) else html)
