"""GET /api/generate-activity-status?activityId=...

Polls the status of an async activity generation job.
Returns { status, html, activityId } when complete,
or { status: "processing" } while still running,
or { status: "error", error: "..." } on failure.
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
        activity_id = params.get("activityId", "").strip()

        if not activity_id:
            send_json(self, {"error": "Missing activityId"}, 400)
            return

        data = kv_get(f"custom_activity:{activity_id}")
        if not data or not isinstance(data, dict):
            send_json(self, {"status": "not_found", "error": "Activity not found"}, 404)
            return

        status = data.get("status", "unknown")

        if status == "complete":
            send_json(self, {
                "status": "complete",
                "activityId": data.get("activityId", activity_id),
                "html": data.get("html", ""),
                "description": data.get("description", ""),
            })
        elif status == "generating":
            send_json(self, {
                "status": "generating",
                "activityId": activity_id,
                "partialHtml": data.get("partialHtml", ""),
            })
        elif status == "error":
            send_json(self, {
                "status": "error",
                "error": data.get("error", "Unknown error"),
            })
        else:
            send_json(self, {
                "status": "processing",
                "activityId": activity_id,
            })
