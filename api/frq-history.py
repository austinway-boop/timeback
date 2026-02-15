"""GET /api/frq-history -- Retrieve past FRQ attempts for a student.

GET /api/frq-history?userId=xxx
Returns { attempts: [ { resultId, subject, questionType, totalScore, maxScore, date }, ... ] }
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from api._kv import kv_list_get


def _send_json(handler, data, status=200):
    body = json.dumps(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body.encode())


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        user_id = params.get("userId", "")

        if not user_id:
            _send_json(self, {"attempts": []})
            return

        attempts = kv_list_get(f"frq_history:{user_id}")

        # Sort by date descending, limit to 20 most recent
        attempts.sort(key=lambda a: a.get("date", 0) if isinstance(a, dict) else 0, reverse=True)
        attempts = attempts[:20]

        _send_json(self, {"attempts": attempts})
