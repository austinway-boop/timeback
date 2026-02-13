"""GET /api/analytics?email=...&startDate=...&endDate=... — Activity facts (EduBridge)

Docs: https://docs.timeback.com/beta/api-reference/beyond-ai/edubridge/analytics/list-all-facts-for-a-given-date-range-by-email-or-studentid
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_with_params, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        email = params.get("email", "")
        student_id = params.get("studentId", "")
        start_date = params.get("startDate", "")
        end_date = params.get("endDate", "")
        timezone = params.get("timezone", "")

        if not email and not student_id:
            send_json(self, {"error": "Provide 'email' or 'studentId' query param"}, 400)
            return

        try:
            api_params = {}
            if email:
                api_params["email"] = email
            if student_id:
                api_params["studentId"] = student_id
            if start_date:
                api_params["startDate"] = start_date
            if end_date:
                api_params["endDate"] = end_date
            if timezone:
                api_params["timezone"] = timezone

            data, status = fetch_with_params(
                "/edubridge/analytics/activity", api_params
            )
            if data:
                send_json(self, data)
            else:
                send_json(self, {"error": f"HTTP {status}", "facts": []}, status)
        except Exception as e:
            send_json(self, {"error": str(e), "facts": []}, 500)
