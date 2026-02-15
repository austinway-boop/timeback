"""GET /api/get-explanations?courseId=... — Student-facing explanation lookup.

Returns AI-generated wrong-answer explanations if the toggle is enabled
for this course and explanations have been generated.
Resolves courseId aliases (student pages may use a different courseId format
than the admin course editor).
"""

from http.server import BaseHTTPRequestHandler

from api._helpers import send_json, get_query_params
from api._kv import kv_get


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
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "").strip()

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        # Try direct toggle check, then resolve alias
        enabled = kv_get(f"explanations_enabled:{course_id}")
        lookup_id = course_id
        if not (enabled is True or enabled == "true"):
            resolved = _resolve_course_id(course_id)
            if resolved != course_id:
                enabled = kv_get(f"explanations_enabled:{resolved}")
                lookup_id = resolved

        if not (enabled is True or enabled == "true"):
            send_json(self, {"enabled": False})
            return

        # Load explanations using resolved courseId
        saved = kv_get(f"explanations:{lookup_id}")
        if not isinstance(saved, dict) or not saved.get("explanations"):
            send_json(self, {"enabled": False})
            return

        send_json(self, {
            "enabled": True,
            "explanations": saved["explanations"],
        })
