"""GET/POST /api/explanation-toggle — Enable/disable answer explanations per course.

POST { courseId, enabled, aliases? } — saves explanations_enabled:{courseId} to KV
     Also saves alias mappings so student pages with different courseIds can find the data.
GET ?courseId=... — returns { enabled: true/false }, resolving aliases if needed.
"""

import json
from http.server import BaseHTTPRequestHandler

from api._helpers import send_json, get_query_params
from api._kv import kv_get, kv_set


def _resolve_course_id(course_id: str) -> str:
    """Resolve a courseId to the canonical one via alias lookup."""
    alias = kv_get(f"explanation_alias:{course_id}")
    if isinstance(alias, str) and alias:
        return alias
    return course_id


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

        # Try direct, then resolve alias
        val = kv_get(f"explanations_enabled:{course_id}")
        if val is None:
            resolved = _resolve_course_id(course_id)
            if resolved != course_id:
                val = kv_get(f"explanations_enabled:{resolved}")

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
        aliases = body.get("aliases", [])

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        kv_set(f"explanations_enabled:{course_id}", enabled)

        # Save alias mappings so student pages can find data under alternative courseIds
        if isinstance(aliases, list):
            for alias in aliases:
                alias = str(alias).strip()
                if alias and alias != course_id:
                    kv_set(f"explanation_alias:{alias}", course_id)
                    kv_set(f"explanations_enabled:{alias}", enabled)

        # Auto-discover aliases from question ID prefixes in the explanations data.
        # Question IDs look like "USHI23-qti104063-q1247901-v1" and the student page
        # uses courseSourcedId like "USHI23-v1". Extract the prefix and create aliases.
        saved = kv_get(f"explanations:{course_id}")
        if isinstance(saved, dict) and saved.get("explanations"):
            prefixes = set()
            for qid in list(saved["explanations"].keys())[:50]:  # sample first 50
                parts = str(qid).split("-")
                if len(parts) >= 2:
                    prefixes.add(parts[0])
            for prefix in prefixes:
                if prefix and prefix != course_id:
                    # Save alias for common enrollment ID patterns
                    for suffix in ["", "-v1", "-v2", "-v3"]:
                        alias_id = prefix + suffix
                        if alias_id != course_id:
                            kv_set(f"explanation_alias:{alias_id}", course_id)
                            kv_set(f"explanations_enabled:{alias_id}", enabled)

        send_json(self, {"enabled": enabled, "courseId": course_id})
