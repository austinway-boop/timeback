"""GET/POST /api/goals — User goals stored in Upstash KV (Redis)

GET  /api/goals?userId=xxx
     → { "goals": { enrollmentId: { endDate, target, excludeNonSchoolDays, dailyXp }, … } }

POST /api/goals  (JSON body)
     { userId, enrollmentId, endDate, target, excludeNonSchoolDays, dailyXp }
     — or to clear: { userId, enrollmentId, clear: true }
     → { "ok": true, "goals": { … } }
"""

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

KV_URL = os.environ.get("KV_REST_API_URL", "")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")


def _kv_headers():
    return {"Authorization": f"Bearer {KV_TOKEN}"}


def _kv_get(user_id: str) -> dict:
    """Read goals:{userId} from Upstash KV. Returns dict or {}."""
    if not KV_URL or not KV_TOKEN:
        return {}
    try:
        resp = requests.get(
            f"{KV_URL}/get/goals:{user_id}",
            headers=_kv_headers(),
            timeout=10,
        )
        data = resp.json()
        result = data.get("result")
        if result:
            return json.loads(result)
    except Exception:
        pass
    return {}


def _kv_set(user_id: str, goals: dict) -> bool:
    """Write goals:{userId} to Upstash KV. Returns True on success."""
    if not KV_URL or not KV_TOKEN:
        return False
    try:
        resp = requests.post(
            f"{KV_URL}",
            headers={**_kv_headers(), "Content-Type": "application/json"},
            json=["SET", f"goals:{user_id}", json.dumps(goals)],
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


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
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        user_id = params.get("userId", "")

        if not user_id:
            _send_json(self, {"error": "Missing userId"}, 400)
            return

        goals = _kv_get(user_id)
        _send_json(self, {"goals": goals})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            _send_json(self, {"error": "Invalid JSON"}, 400)
            return

        user_id = body.get("userId", "")
        enrollment_id = body.get("enrollmentId", "")

        if not user_id or not enrollment_id:
            _send_json(self, {"error": "Missing userId or enrollmentId"}, 400)
            return

        # Read current goals
        goals = _kv_get(user_id)

        if body.get("clear"):
            # Remove this enrollment's goal
            goals.pop(enrollment_id, None)
        else:
            # Merge goal data
            goal_data = {}
            if body.get("endDate"):
                goal_data["endDate"] = body["endDate"]
            if body.get("target"):
                goal_data["target"] = int(body["target"])
            if "excludeNonSchoolDays" in body:
                goal_data["excludeNonSchoolDays"] = bool(body["excludeNonSchoolDays"])
            if body.get("dailyXp"):
                goal_data["dailyXp"] = int(body["dailyXp"])
            goals[enrollment_id] = goal_data

        ok = _kv_set(user_id, goals)
        if ok:
            _send_json(self, {"ok": True, "goals": goals})
        else:
            _send_json(self, {"error": "Failed to save to KV"}, 500)
