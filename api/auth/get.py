"""GET /api/get-auth — Returns full auth token for local use."""
from http.server import BaseHTTPRequestHandler
from api._helpers import get_token, send_json

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            token = get_token()
            send_json(self, {"token": token})
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
