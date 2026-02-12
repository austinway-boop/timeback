"""POST /api/submit-result — Record an AssessmentResult via OneRoster Gradebook.

Creates a new assessment result for a student on a given assessment line item.
Uses the same Cognito auth as all other API calls.

Body: {
  "studentSourcedId": "...",
  "assessmentLineItemSourcedId": "...",   // resId or testId from course content
  "score": 85,                            // numeric score (accuracy %)
  "scoreStatus": "fully graded",
  "comment": "optional notes",
  "metadata": {}                          // optional extra metadata
}
"""

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params


# OneRoster gradebook paths to try
_RESULTS_PATHS = [
    "/ims/oneroster/gradebook/v1p2/assessmentResults/",
    "/ims/oneroster/v1p2/assessmentResults/",
]


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
            send_json(
                self,
                {"error": "Missing studentSourcedId or assessmentLineItemSourcedId"},
                400,
            )
            return

        result_id = _uuid()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        payload = {
            "assessmentResult": {
                "sourcedId": result_id,
                "status": "active",
                "student": {"sourcedId": student_id},
                "assessmentLineItem": {"sourcedId": line_item_id},
                "score": score,
                "scoreStatus": score_status,
                "scoreDate": now,
            }
        }
        if comment:
            payload["assessmentResult"]["comment"] = comment
        if metadata:
            payload["assessmentResult"]["metadata"] = metadata

        headers = api_headers()
        last_error = None

        for path in _RESULTS_PATHS:
            try:
                url = f"{API_BASE}{path}"
                resp = requests.post(url, headers=headers, json=payload, timeout=15)

                if resp.status_code == 401:
                    headers = api_headers()
                    resp = requests.post(url, headers=headers, json=payload, timeout=15)

                if resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                    except Exception:
                        data = {}
                    send_json(
                        self,
                        {
                            "status": "success",
                            "sourcedId": result_id,
                            "response": data,
                        },
                        201,
                    )
                    return
                else:
                    last_error = {
                        "path": path,
                        "httpStatus": resp.status_code,
                        "body": resp.text[:300],
                    }
            except Exception as e:
                last_error = {"path": path, "error": str(e)}

        send_json(
            self,
            {
                "status": "error",
                "message": "All OneRoster paths failed",
                "lastError": last_error,
            },
            502,
        )
