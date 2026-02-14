"""GET/POST /api/quiz-progress — Persist quiz progress to KV store.

Saves and restores static (QTI) quiz progress so students don't lose
their place on page reload.

GET  ?studentId=...&quizId=...  → retrieve saved progress
POST { studentId, quizId, progress: { ... } } → save progress

KV key: quiz_prog:{studentId}:{quizId}
TTL: 30 days (auto-expires stale data)
"""

import json
import os
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import send_json, get_query_params

KV_URL = os.environ.get("KV_REST_API_URL", "")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")
TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


def _kv_headers():
    return {"Authorization": f"Bearer {KV_TOKEN}", "Content-Type": "application/json"}


def _kv_get(key: str):
    if not KV_URL or not KV_TOKEN:
        return None
    try:
        resp = requests.get(f"{KV_URL}/get/{key}", headers=_kv_headers(), timeout=8)
        result = resp.json().get("result")
        if result is not None:
            return json.loads(result) if isinstance(result, str) else result
    except Exception:
        pass
    return None


def _kv_set(key: str, value, ttl: int = TTL_SECONDS) -> bool:
    if not KV_URL or not KV_TOKEN:
        return False
    try:
        resp = requests.post(
            KV_URL,
            headers=_kv_headers(),
            json=["SET", key, json.dumps(value), "EX", ttl],
            timeout=8,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _kv_delete(key: str) -> bool:
    if not KV_URL or not KV_TOKEN:
        return False
    try:
        resp = requests.post(
            KV_URL,
            headers=_kv_headers(),
            json=["DEL", key],
            timeout=8,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _make_key(student_id: str, quiz_id: str) -> str:
    return f"quiz_prog:{student_id}:{quiz_id}"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        student_id = params.get("studentId", "").strip()
        quiz_id = params.get("quizId", "").strip()

        if not student_id or not quiz_id:
            send_json(self, {"error": "Missing studentId or quizId"}, 400)
            return

        data = _kv_get(_make_key(student_id, quiz_id))
        if data:
            send_json(self, {"found": True, "progress": data})
        else:
            send_json(self, {"found": False})

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        student_id = body.get("studentId", "").strip()
        quiz_id = body.get("quizId", "").strip()
        progress = body.get("progress")

        if not student_id or not quiz_id:
            send_json(self, {"error": "Missing studentId or quizId"}, 400)
            return
        if not isinstance(progress, dict):
            send_json(self, {"error": "progress must be an object"}, 400)
            return

        ok = _kv_set(_make_key(student_id, quiz_id), progress)
        send_json(self, {"saved": ok}, 200 if ok else 502)

    def do_DELETE(self):
        params = get_query_params(self)
        student_id = params.get("studentId", "").strip()
        quiz_id = params.get("quizId", "").strip()

        if not student_id or not quiz_id:
            send_json(self, {"error": "Missing studentId or quizId"}, 400)
            return

        ok = _kv_delete(_make_key(student_id, quiz_id))
        send_json(self, {"deleted": ok})
