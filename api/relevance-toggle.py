"""GET/POST /api/relevance-toggle — Toggle hiding of AI-flagged irrelevant questions.

GET  ?courseId=...  → { enabled: true/false }
POST { courseId, enabled } or { courseId, questionId, hidden }

When ``enabled`` is provided:
  - true  → push all AI-flagged bad question IDs to ``ai_irrelevant_questions``
  - false → remove them

When ``questionId`` + ``hidden`` are provided, toggle a single question.
"""

import json
from http.server import BaseHTTPRequestHandler

from api._helpers import send_json, get_query_params
from api._kv import kv_get, kv_set, kv_list_get, kv_list_push, kv_list_remove


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
        val = kv_get(f"relevance_enabled:{course_id}")
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
        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        # ── Single-question toggle ────────────────────────────────────
        question_id = body.get("questionId", "").strip()
        if question_id:
            hidden = body.get("hidden", True)
            current = kv_list_get("ai_irrelevant_questions")
            if hidden and question_id not in current:
                kv_list_push("ai_irrelevant_questions", question_id)
            elif not hidden and question_id in current:
                kv_list_remove("ai_irrelevant_questions", question_id)
            send_json(self, {"ok": True, "questionId": question_id, "hidden": hidden})
            return

        # ── Course-wide toggle ────────────────────────────────────────
        enabled = body.get("enabled")
        if enabled is None:
            send_json(self, {"error": "Missing 'enabled' or 'questionId'"}, 400)
            return

        # Persist toggle state
        kv_set(f"relevance_enabled:{course_id}", bool(enabled))

        # Load analysis results
        analysis = kv_get(f"relevance_analysis:{course_id}")
        if not isinstance(analysis, dict) or not analysis.get("results"):
            send_json(self, {"ok": True, "enabled": enabled, "changed": 0})
            return

        results = analysis["results"]
        bad_ids = [
            qid for qid, info in results.items()
            if isinstance(info, dict) and not info.get("relevant", True)
        ]

        current = kv_list_get("ai_irrelevant_questions")
        changed = 0

        if enabled:
            for qid in bad_ids:
                if qid not in current:
                    kv_list_push("ai_irrelevant_questions", qid)
                    current.append(qid)
                    changed += 1
        else:
            for qid in bad_ids:
                if qid in current:
                    kv_list_remove("ai_irrelevant_questions", qid)
                    changed += 1

        send_json(self, {"ok": True, "enabled": enabled, "changed": changed, "badIds": bad_ids})
