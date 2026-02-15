"""GET /api/article-cleanup-status?courseId=...

Polls the status of an article cleanup job. Returns:
  - { status: "processing", totalLessons, processedLessons, ... } while running
  - { status: "done", results: { ... }, ... } when complete
  - { status: "error", error: "..." } on failure
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

        data = kv_get(f"article_cleanup:{course_id}")
        if not data or not isinstance(data, dict):
            send_json(self, {"status": "not_started"})
            return

        send_json(self, data)
