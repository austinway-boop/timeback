"""GET/POST /api/reporting-config — Manage question-reporting toggles.

GET  /api/reporting-config?studentId=xxx
     → { "enabled": true/false, "globalEnabled": true, "studentOverride": null }

POST /api/reporting-config  (JSON body)
     { "global": true, "enabled": true }            — set global toggle
     { "studentId": "xxx", "enabled": false }        — set per-student override
     { "studentId": "xxx", "clear": true }           — remove per-student override
     → { "ok": true, "config": { … } }
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from api._kv import kv_get, kv_set

CONFIG_KEY = "reporting_config"

# Default config structure:
# { "globalEnabled": true, "students": { "<id>": true/false } }


def _load_config() -> dict:
    cfg = kv_get(CONFIG_KEY)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("globalEnabled", True)
    cfg.setdefault("students", {})
    return cfg


def _is_enabled(cfg: dict, student_id: str) -> bool:
    """Resolve whether reporting is enabled for a specific student."""
    override = cfg.get("students", {}).get(student_id)
    if override is not None:
        return bool(override)
    return bool(cfg.get("globalEnabled", True))


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

        cfg = _load_config()

        result = {
            "globalEnabled": cfg["globalEnabled"],
            "studentOverride": cfg["students"].get(student_id) if student_id else None,
            "enabled": _is_enabled(cfg, student_id) if student_id else cfg["globalEnabled"],
            "config": cfg,
        }
        _send_json(self, result)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            _send_json(self, {"error": "Invalid JSON"}, 400)
            return

        cfg = _load_config()

        if body.get("global"):
            # Set global toggle
            cfg["globalEnabled"] = bool(body.get("enabled", True))
        elif body.get("studentId"):
            sid = body["studentId"]
            if body.get("clear"):
                cfg["students"].pop(sid, None)
            else:
                cfg["students"][sid] = bool(body.get("enabled", True))
        else:
            _send_json(self, {"error": "Provide 'global' or 'studentId'"}, 400)
            return

        ok = kv_set(CONFIG_KEY, cfg)
        if ok:
            _send_json(self, {"ok": True, "config": cfg})
        else:
            _send_json(self, {"error": "Failed to save config"}, 500)
