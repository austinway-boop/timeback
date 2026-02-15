"""GET /api/frq-grade-status -- Poll grading status for an FRQ submission.

GET /api/frq-grade-status?resultId=frq_r_xxxx
Returns { status: "processing"|"complete"|"error", result?: {...}, error?: "..." }
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from api._kv import kv_get


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
        result_id = params.get("resultId", "")

        if not result_id:
            _send_json(self, {"error": "Missing resultId"}, 400)
            return

        data = kv_get(f"frq_result:{result_id}")
        if not isinstance(data, dict):
            _send_json(self, {"status": "processing"})
            return

        status = data.get("status", "processing")

        if status == "complete":
            _send_json(self, {
                "status": "complete",
                "result": data.get("result", {}),
            })
        elif status == "error":
            _send_json(self, {
                "status": "error",
                "error": data.get("error", "Unknown error"),
            })
        else:
            _send_json(self, {"status": "processing"})
