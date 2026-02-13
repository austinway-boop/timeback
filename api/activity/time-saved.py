"""GET /api/time-saved?userId=... — Total time saved this school year (EduBridge)

Docs: https://docs.timeback.com/beta/api-reference/beyond-ai/edubridge/enrollments/get-total-time-saved-for-a-student-this-school-year
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_one, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        user_id = params.get("userId", "")

        if not user_id:
            send_json(self, {"error": "Missing 'userId' query param"}, 400)
            return

        try:
            data, status = fetch_one(f"/edubridge/time-saved/user/{user_id}")
            if data:
                send_json(self, data)
            else:
                send_json(self, {"error": f"HTTP {status}"}, status)
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
