"""GET/POST /api/skill-mapping-toggle — Enable/disable skill mapping per course.

POST { courseId, enabled } — saves skill_mapping_enabled:{courseId} to KV
GET ?courseId=... — returns { enabled: true/false }
GET ?list=true — returns all enabled course IDs
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
        list_all = params.get("list", "").strip().lower()

        if list_all == "true":
            # Return all enabled course IDs
            enabled_list = kv_get("skill_mapping_enabled_courses") or []
            if not isinstance(enabled_list, list):
                enabled_list = []
            send_json(self, {"courses": enabled_list})
            return

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        val = kv_get(f"skill_mapping_enabled:{course_id}")
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

        kv_set(f"skill_mapping_enabled:{course_id}", enabled)

        # Maintain a list of all enabled courses for the list endpoint
        enabled_list = kv_get("skill_mapping_enabled_courses") or []
        if not isinstance(enabled_list, list):
            enabled_list = []
        if enabled and course_id not in enabled_list:
            enabled_list.append(course_id)
            kv_set("skill_mapping_enabled_courses", enabled_list)
        elif not enabled and course_id in enabled_list:
            enabled_list.remove(course_id)
            kv_set("skill_mapping_enabled_courses", enabled_list)

        send_json(self, {"enabled": enabled, "courseId": course_id})
