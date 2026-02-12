"""POST /api/submit-result — Record a result via OneRoster Gradebook.

Tries multiple OneRoster strategies to find one that works:
  1. PUT  /assessmentResults/{id}  (upsert - hypothesis A)
  2. POST /assessmentResults/       (create - original)
  3. PUT  /results/{id}             (upsert via results - hypothesis B)
  4. POST /results/                 (create via results - hypothesis B)
"""

import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params

LOG_PATH = "/Users/austinway/Desktop/hack/.cursor/debug.log"


def _log(message, data=None, hypothesis=None):
    """Append a debug log line."""
    import time
    entry = {
        "timestamp": int(time.time() * 1000),
        "location": "submit-result.py",
        "message": message,
        "data": data or {},
    }
    if hypothesis:
        entry["hypothesisId"] = hypothesis
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _uuid():
    import uuid
    return str(uuid.uuid4())


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

        student_id = body.get("studentSourcedId", "")
        line_item_id = body.get("assessmentLineItemSourcedId", "")
        score = body.get("score")
        score_status = body.get("scoreStatus", "fully graded")
        comment = body.get("comment", "")
        metadata = body.get("metadata") or {}

        if not student_id or not line_item_id:
            send_json(self, {"error": "Missing studentSourcedId or assessmentLineItemSourcedId"}, 400)
            return

        result_id = _uuid()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # #region agent log
        _log("submit-result called", {
            "studentId": student_id,
            "lineItemId": line_item_id,
            "score": score,
            "resultId": result_id,
        }, "entry")
        # #endregion

        headers = api_headers()

        # ── Strategy list: try each until one succeeds ──
        strategies = [
            # Hypothesis A: PUT upsert to assessmentResults/{id}
            {
                "name": "PUT assessmentResults (upsert)",
                "hypothesis": "A",
                "method": "PUT",
                "url": f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentResults/{result_id}",
                "payload": {
                    "assessmentResult": {
                        "sourcedId": result_id,
                        "status": "active",
                        "student": {"sourcedId": student_id},
                        "assessmentLineItem": {"sourcedId": line_item_id},
                        "score": score,
                        "scoreStatus": score_status,
                        "scoreDate": now,
                        "comment": comment or None,
                        "metadata": metadata or None,
                    }
                },
            },
            # Hypothesis B: PUT upsert to results/{id} with lineItem instead of assessmentLineItem
            {
                "name": "PUT results (upsert)",
                "hypothesis": "B",
                "method": "PUT",
                "url": f"{API_BASE}/ims/oneroster/gradebook/v1p2/results/{result_id}",
                "payload": {
                    "result": {
                        "sourcedId": result_id,
                        "status": "active",
                        "student": {"sourcedId": student_id},
                        "lineItem": {"sourcedId": line_item_id},
                        "score": score,
                        "scoreStatus": score_status,
                        "scoreDate": now,
                        "comment": comment or None,
                        "metadata": metadata or None,
                    }
                },
            },
            # Original: POST to assessmentResults
            {
                "name": "POST assessmentResults",
                "hypothesis": "A_post",
                "method": "POST",
                "url": f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentResults/",
                "payload": {
                    "assessmentResult": {
                        "sourcedId": result_id,
                        "status": "active",
                        "student": {"sourcedId": student_id},
                        "assessmentLineItem": {"sourcedId": line_item_id},
                        "score": score,
                        "scoreStatus": score_status,
                        "scoreDate": now,
                        "comment": comment or None,
                        "metadata": metadata or None,
                    }
                },
            },
            # Hypothesis B: POST to results
            {
                "name": "POST results",
                "hypothesis": "B_post",
                "method": "POST",
                "url": f"{API_BASE}/ims/oneroster/gradebook/v1p2/results/",
                "payload": {
                    "result": {
                        "sourcedId": result_id,
                        "status": "active",
                        "student": {"sourcedId": student_id},
                        "lineItem": {"sourcedId": line_item_id},
                        "score": score,
                        "scoreStatus": score_status,
                        "scoreDate": now,
                        "comment": comment or None,
                        "metadata": metadata or None,
                    }
                },
            },
        ]

        attempts = []
        for strat in strategies:
            attempt = {"name": strat["name"], "hypothesis": strat["hypothesis"]}
            try:
                method = strat["method"]
                url = strat["url"]
                payload = strat["payload"]
                attempt["url"] = url
                attempt["method"] = method

                if method == "PUT":
                    resp = requests.put(url, headers=headers, json=payload, timeout=15)
                else:
                    resp = requests.post(url, headers=headers, json=payload, timeout=15)

                if resp.status_code == 401:
                    headers = api_headers()
                    if method == "PUT":
                        resp = requests.put(url, headers=headers, json=payload, timeout=15)
                    else:
                        resp = requests.post(url, headers=headers, json=payload, timeout=15)

                attempt["httpStatus"] = resp.status_code
                attempt["body"] = resp.text[:500]

                if resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                    except Exception:
                        data = {}
                    send_json(self, {
                        "status": "success",
                        "strategy": strat["name"],
                        "sourcedId": result_id,
                        "response": data,
                        "attempts": attempts + [attempt],
                    }, 201)
                    return

            except Exception as e:
                attempt["error"] = str(e)

            attempts.append(attempt)

        # All strategies failed — return ALL attempt details
        send_json(self, {
            "status": "error",
            "message": "All OneRoster result strategies failed",
            "attempts": attempts,
        }, 502)
