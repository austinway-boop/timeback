"""GET/POST /api/report-queue — Admin report queue and actions.

GET  /api/report-queue
     → { "reports": [ { id, studentId, questionText, verdict, … }, … ] }

POST /api/report-queue  (JSON body)
     { "reportId": "rpt_...", "action": "mark_good"|"mark_bad" }
     → { "ok": true, "report": { … } }
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from _kv import kv_get, kv_set, kv_list_get, kv_list_push, kv_list_remove


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

        # Sort: AI-flagged and pending first, then by date descending
        status_order = {"ai_flagged_bad": 0, "pending_review": 1, "ai_error": 2, "resolved": 3}
        reports.sort(key=lambda r: (
            status_order.get(r.get("status", ""), 9),
            -(hash(r.get("date", "")) & 0xFFFFFFFF),
        ))

        # Compute stats
        stats = {
            "total": len(reports),
            "pending": sum(1 for r in reports if r.get("status") in ("pending_review", "ai_error")),
            "aiFlagged": sum(1 for r in reports if r.get("status") == "ai_flagged_bad"),
            "valid": sum(1 for r in reports if r.get("verdict") == "valid"),
            "invalid": sum(1 for r in reports if r.get("verdict") == "invalid"),
            "humanReviewed": sum(1 for r in reports if r.get("adminAction") in ("mark_good", "mark_bad")),
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

        if action == "mark_good":
            # Admin confirms question is valid — remove from globally hidden
            report["adminAction"] = "mark_good"
            report["adminNote"] = "Human reviewed — question is valid"
            report["status"] = "resolved"
            if question_id:
                kv_list_remove("globally_hidden_questions", question_id)
            kv_set(f"report:{report_id}", report)
            _send_json(self, {"ok": True, "report": report})

        elif action == "mark_bad":
            # Admin confirms question is bad — permanently remove
            report["adminAction"] = "mark_bad"
            report["adminNote"] = "Human reviewed — question permanently removed"
            report["status"] = "resolved"
            if question_id:
                # Add to permanent bad list
                bad = kv_list_get("bad_questions")
                if question_id not in bad:
                    kv_list_push("bad_questions", question_id)
                # Also keep in globally hidden so it stays filtered
                hidden = kv_list_get("globally_hidden_questions")
                if question_id not in hidden:
                    kv_list_push("globally_hidden_questions", question_id)
            kv_set(f"report:{report_id}", report)
            _send_json(self, {"ok": True, "report": report})

        else:
            _send_json(self, {"error": f"Unknown action: {action}"}, 400)
