"""GET/POST /api/report-queue — Admin report queue and actions.

GET  /api/report-queue
     → { "reports": [ { id, studentId, questionText, verdict, … }, … ] }

POST /api/report-queue  (JSON body)
     { "reportId": "rpt_...", "action": "remove"|"regenerate"|"mark_correct" }
     → { "ok": true, "report": { … } }
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from _kv import kv_get, kv_set, kv_list_get


def _send_json(handler, data, status=200):
    body = json.dumps(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body.encode())


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Return all reports from the queue with full details."""
        report_ids = kv_list_get("report_queue")

        reports = []
        for rid in report_ids:
            report = kv_get(f"report:{rid}")
            if isinstance(report, dict):
                reports.append(report)

        # Sort: pending first, then by date descending
        status_order = {"pending_review": 0, "ai_error": 1, "resolved": 2}
        reports.sort(key=lambda r: (
            status_order.get(r.get("status", ""), 9),
            -(hash(r.get("date", "")) & 0xFFFFFFFF),
        ))

        # Compute stats
        stats = {
            "total": len(reports),
            "pending": sum(1 for r in reports if r.get("status") in ("pending_review", "ai_error")),
            "valid": sum(1 for r in reports if r.get("verdict") == "valid"),
            "invalid": sum(1 for r in reports if r.get("verdict") == "invalid"),
            "humanReviewed": sum(1 for r in reports if r.get("adminAction") == "mark_correct"),
        }

        _send_json(self, {"reports": reports, "stats": stats})

    def do_POST(self):
        """Handle admin actions on a report."""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            _send_json(self, {"error": "Invalid JSON"}, 400)
            return

        report_id = body.get("reportId", "")
        action = body.get("action", "")

        if not report_id or not action:
            _send_json(self, {"error": "Missing reportId or action"}, 400)
            return

        report = kv_get(f"report:{report_id}")
        if not isinstance(report, dict):
            _send_json(self, {"error": "Report not found"}, 404)
            return

        question_id = report.get("questionId", "")

        if action == "remove":
            # Mark question as hidden for this student
            report["adminAction"] = "remove"
            report["adminNote"] = "Question removed from student's pool"
            student_id = report.get("studentId", "")
            if student_id and question_id:
                hidden = kv_get(f"hidden_questions:{student_id}") or []
                if question_id not in hidden:
                    hidden.append(question_id)
                    kv_set(f"hidden_questions:{student_id}", hidden)
            kv_set(f"report:{report_id}", report)
            _send_json(self, {"ok": True, "report": report})

        elif action == "regenerate":
            # Flag for regeneration (future enhancement)
            report["adminAction"] = "regenerate"
            report["adminNote"] = "Flagged for question regeneration"
            student_id = report.get("studentId", "")
            if student_id and question_id:
                regen = kv_get(f"regen_questions:{student_id}") or []
                if question_id not in regen:
                    regen.append(question_id)
                    kv_set(f"regen_questions:{student_id}", regen)
            kv_set(f"report:{report_id}", report)
            _send_json(self, {"ok": True, "report": report})

        elif action == "mark_correct":
            # Increment human review count on this question
            flags = kv_get(f"question_flags:{question_id}") or {}
            if not isinstance(flags, dict):
                flags = {}
            flags["humanReviewCount"] = flags.get("humanReviewCount", 0) + 1
            flags["lastReviewedBy"] = body.get("adminId", "admin")
            kv_set(f"question_flags:{question_id}", flags)

            report["adminAction"] = "mark_correct"
            report["adminNote"] = f"Human verified as correct (review #{flags['humanReviewCount']})"
            kv_set(f"report:{report_id}", report)
            _send_json(self, {"ok": True, "report": report, "humanReviewCount": flags["humanReviewCount"]})

        else:
            _send_json(self, {"error": f"Unknown action: {action}"}, 400)
