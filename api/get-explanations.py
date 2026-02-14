"""GET /api/get-explanations?courseId=... — Student-facing explanation lookup.

Returns AI-generated wrong-answer explanations if the toggle is enabled
for this course and explanations have been generated.
"""

from http.server import BaseHTTPRequestHandler

from api._helpers import send_json, get_query_params
from api._kv import kv_get


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "").strip()

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        # Check toggle
        enabled = kv_get(f"explanations_enabled:{course_id}")
        if not (enabled is True or enabled == "true"):
            send_json(self, {"enabled": False})
            return

        # Load explanations
        saved = kv_get(f"explanations:{course_id}")
        if not isinstance(saved, dict) or not saved.get("explanations"):
            send_json(self, {"enabled": False})
            return

        send_json(self, {
            "enabled": True,
            "explanations": saved["explanations"],
        })
