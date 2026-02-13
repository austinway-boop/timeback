"""POST /api/caliper-event — Proxy Caliper events to the Alpha Caliper API.

Accepts a JSON body with an array of Caliper event objects and wraps them
in a Caliper Envelope before forwarding to caliper.alpha-1edtech.ai.

Auth uses the same Cognito credentials as the rest of the platform
(TIMEBACK_CLIENT_ID / TIMEBACK_CLIENT_SECRET).

Body:  { "data": [ { ...caliper event... }, ... ] }
"""

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from api._helpers import get_token, send_json

import requests

CALIPER_URL = "https://caliper.alpha-1edtech.ai/caliper/event"
SENSOR_ID = "https://alphalearn.alpha.school"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON body"}, 400)
            return

        events = body.get("data") or body.get("events") or []
        if not events:
            send_json(self, {"error": "No events provided"}, 400)
            return

        # Build Caliper Envelope
        envelope = {
            "sensor": SENSOR_ID,
            "sendTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "dataVersion": "http://purl.imsglobal.org/ctx/caliper/v1p2",
            "data": events,
        }

        try:
            token = get_token()
            resp = requests.post(
                CALIPER_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=envelope,
                timeout=15,
            )

            if resp.status_code in (200, 201, 204):
                result = {}
                try:
                    result = resp.json()
                except Exception:
                    pass
                send_json(self, {
                    "status": "success",
                    "sent": len(events),
                    "response": result,
                })
            else:
                error_body = ""
                try:
                    error_body = resp.text[:500]
                except Exception:
                    pass
                send_json(self, {
                    "status": "error",
                    "httpStatus": resp.status_code,
                    "body": error_body,
                    "sent": 0,
                }, resp.status_code if resp.status_code < 500 else 502)
        except Exception as e:
            send_json(self, {"status": "error", "error": str(e), "sent": 0}, 500)
