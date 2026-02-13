"""GET /api/enrollment-analytics?enrollmentId=...&startDate=...&endDate=... — Per-enrollment facts (EduBridge)

Docs: https://docs.timeback.com/beta/api-reference/beyond-ai/edubridge/analytics/list-all-facts-for-a-given-enrollment
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_with_params, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        enrollment_id = params.get("enrollmentId", "")

        if not enrollment_id:
            send_json(self, {"error": "Missing 'enrollmentId' query param"}, 400)
            return

        try:
            api_params = {}
            start_date = params.get("startDate", "")
            end_date = params.get("endDate", "")
            timezone = params.get("timezone", "")

            if start_date:
                api_params["startDate"] = start_date
            if end_date:
                api_params["endDate"] = end_date
            if timezone:
                api_params["timezone"] = timezone

            data, status = fetch_with_params(
                f"/edubridge/analytics/enrollment/{enrollment_id}", api_params
            )
            if data:
                send_json(self, data)
            else:
                send_json(
                    self,
                    {"error": f"HTTP {status}", "facts": {}, "factsByApp": {}},
                    status,
                )
        except Exception as e:
            send_json(self, {"error": str(e), "facts": {}, "factsByApp": {}}, 500)
