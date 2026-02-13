"""GET/POST /api/report-question — Submit and query question reports.

GET  /api/report-question?studentId=xxx
     → { "enabled": true, "todayCount": 2, "limit": 5 }

POST /api/report-question  (JSON body)
     {
       studentId, questionId, questionText, choices, correctId,
       reason, customText, videoUrl, articleContent, lessonTitle
     }
     → { "ok": true, "reportId": "rpt_..." }
"""

import json
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from api._kv import kv_get, kv_set, kv_list_get, kv_list_push

DAILY_LIMIT = 5
CONFIG_KEY = "reporting_config"


def _load_config() -> dict:
    cfg = kv_get(CONFIG_KEY)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("globalEnabled", True)
    cfg.setdefault("students", {})
    return cfg


def _is_enabled(cfg: dict, student_id: str) -> bool:
    override = cfg.get("students", {}).get(student_id)
    if override is not None:
        return bool(override)
    return bool(cfg.get("globalEnabled", True))


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _count_today(student_id: str) -> int:
    """Count how many reports this student submitted today."""
    report_ids = kv_list_get(f"student_reports:{student_id}")
    today = _today_str()
    count = 0
    for rid in report_ids:
        report = kv_get(f"report:{rid}")
        if isinstance(report, dict) and report.get("date", "")[:10] == today:
            count += 1
    return count


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
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        student_id = params.get("studentId", "")

        if not student_id:
            _send_json(self, {"error": "Missing studentId"}, 400)
            return

        cfg = _load_config()
        enabled = _is_enabled(cfg, student_id)
        today_count = _count_today(student_id) if enabled else 0

        _send_json(self, {
            "enabled": enabled,
            "todayCount": today_count,
            "limit": DAILY_LIMIT,
        })

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            _send_json(self, {"error": "Invalid JSON"}, 400)
            return

        student_id = body.get("studentId", "")
        question_id = body.get("questionId", "")

        if not student_id or not question_id:
            _send_json(self, {"error": "Missing studentId or questionId"}, 400)
            return

        # Check if reporting is enabled
        cfg = _load_config()
        if not _is_enabled(cfg, student_id):
            _send_json(self, {"error": "Reporting is disabled"}, 403)
            return

        # Rate limit
        today_count = _count_today(student_id)
        if today_count >= DAILY_LIMIT:
            _send_json(self, {"error": "Daily report limit reached", "limit": DAILY_LIMIT}, 429)
            return

        # Check if question has been human-reviewed 3+ times (auto-reject)
        question_flags = kv_get(f"question_flags:{question_id}")
        if isinstance(question_flags, dict) and question_flags.get("humanReviewCount", 0) >= 3:
            # Silently accept but auto-resolve as invalid (anti-gaming)
            report_id = f"rpt_{uuid.uuid4().hex[:12]}"
            report = {
                "id": report_id,
                "studentId": student_id,
                "questionId": question_id,
                "questionText": body.get("questionText", ""),
                "choices": body.get("choices", []),
                "correctId": body.get("correctId", ""),
                "reason": body.get("reason", ""),
                "customText": body.get("customText", ""),
                "videoUrl": body.get("videoUrl", ""),
                "articleContent": body.get("articleContent", ""),
                "lessonTitle": body.get("lessonTitle", ""),
                "date": datetime.now(timezone.utc).isoformat(),
                "status": "resolved",
                "verdict": "invalid",
                "aiReasoning": "Question has been human-reviewed and verified as correct.",
                "pointsAwarded": 0,
                "autoRejected": True,
            }
            kv_set(f"report:{report_id}", report)
            kv_list_push(f"student_reports:{student_id}", report_id)
            kv_list_push("report_queue", report_id)
            _send_json(self, {"ok": True, "reportId": report_id})
            return

        # Create report
        report_id = f"rpt_{uuid.uuid4().hex[:12]}"
        report = {
            "id": report_id,
            "studentId": student_id,
            "questionId": question_id,
            "questionText": body.get("questionText", ""),
            "choices": body.get("choices", []),
            "correctId": body.get("correctId", ""),
            "reason": body.get("reason", ""),
            "customText": body.get("customText", ""),
            "videoUrl": body.get("videoUrl", ""),
            "articleContent": body.get("articleContent", ""),
            "lessonTitle": body.get("lessonTitle", ""),
            "answeredCorrectly": bool(body.get("answeredCorrectly", False)),
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "pending_review",
            "verdict": None,
            "aiReasoning": None,
            "pointsAwarded": 0,
        }

        kv_set(f"report:{report_id}", report)
        kv_list_push(f"student_reports:{student_id}", report_id)
        kv_list_push("report_queue", report_id)

        _send_json(self, {"ok": True, "reportId": report_id})
