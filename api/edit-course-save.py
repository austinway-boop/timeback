"""POST /api/edit-course-save

Saves the editable course structure to KV.
Body: { courseId: string, units: [...] }
"""

import json
import time
from http.server import BaseHTTPRequestHandler

from api._helpers import send_json
from api._kv import kv_set


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        course_id = body.get("courseId", "").strip()
        units = body.get("units")

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        if units is None or not isinstance(units, list):
            send_json(self, {"error": "Missing or invalid units array"}, 400)
            return

        data = {
            "courseId": course_id,
            "lastModified": time.time(),
            "units": units,
        }

        ok = kv_set(f"course_edit:{course_id}", data)
        if ok:
            send_json(self, {"success": True, "lastModified": data["lastModified"]})
        else:
            send_json(self, {"error": "Failed to save to KV"}, 500)
