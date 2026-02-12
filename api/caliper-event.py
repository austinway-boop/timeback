"""POST /api/caliper-event — Proxy Caliper events to TimeBack Platform.

Accepts a JSON body containing one or more Caliper events and forwards them
to the TimeBack Caliper endpoint with proper OAuth authentication.

Body:
  Single event:  { "event": { ... caliper event ... } }
  Batch events:  { "events": [ { ... }, { ... } ] }
"""

import json
from http.server import BaseHTTPRequestHandler
from api._helpers import get_token, send_json, ED_APP_ID

import requests

CALIPER_URL = "https://platform.timeback.com/events/1.0/"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Return the edApp ID so the frontend can build events."""
        send_json(self, {"edAppId": ED_APP_ID})

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON body"}, 400)
            return

        events = body.get("events") or []
        if not events and body.get("event"):
            events = [body["event"]]

        if not events:
            send_json(self, {"error": "No events provided"}, 400)
            return

        if not ED_APP_ID:
            # Still save locally — just can't forward to platform
            send_json(
                self,
                {
                    "warning": "TIMEBACK_ED_APP_ID not configured, events not forwarded",
                    "sent": 0,
                    "total": len(events),
                },
            )
            return

        token = get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        sent = 0
        errors = []
        for evt in events:
            # Inject edApp if not set
            if not evt.get("edApp"):
                evt["edApp"] = f"urn:uuid:{ED_APP_ID}"

            try:
                resp = requests.post(
                    CALIPER_URL, headers=headers, json=evt, timeout=10
                )
                if resp.status_code in (200, 201, 204):
                    sent += 1
                else:
                    errors.append(
                        {
                            "status": resp.status_code,
                            "body": resp.text[:200],
                            "eventId": evt.get("id", ""),
                        }
                    )
            except Exception as e:
                errors.append({"error": str(e), "eventId": evt.get("id", "")})

        send_json(
            self,
            {"sent": sent, "total": len(events), "errors": errors if errors else None},
        )
