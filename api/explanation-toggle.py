"""GET/POST /api/explanation-toggle — Enable/disable answer explanations per course.

POST { courseId, enabled } — saves explanations_enabled:{courseId} to KV
GET ?courseId=... — returns { enabled: true/false }
"""

import json
from http.server import BaseHTTPRequestHandler

from api._helpers import send_json, get_query_params
from api._kv import kv_get, kv_set


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "").strip()

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        val = kv_get(f"explanations_enabled:{course_id}")
        send_json(self, {"enabled": val is True or val == "true", "courseId": course_id})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        course_id = body.get("courseId", "").strip()
        enabled = bool(body.get("enabled", False))

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        kv_set(f"explanations_enabled:{course_id}", enabled)
        send_json(self, {"enabled": enabled, "courseId": course_id})
