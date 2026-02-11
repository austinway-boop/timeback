"""GET /api/user-lookup?email=... — Fast single-user lookup by email.

Uses OneRoster filter param instead of fetching all users.
Returns one user object or 404.
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_with_params, parse_user, send_json, get_query_params


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        email = params.get("email", "").strip()

        if not email:
            send_json(self, {"error": "Missing 'email' query param"}, 400)
            return

        try:
            # OneRoster v1p2 supports filter expressions
            data, status = fetch_with_params(
                "/ims/oneroster/rostering/v1p2/users",
                {"filter": f"email='{email}'", "limit": 1},
            )

            if data:
                # OneRoster wraps the result in {"users": [...]}
                users_list = data.get("users", [])
                if not users_list:
                    # Sometimes the response nests differently
                    for key in data:
                        if isinstance(data[key], list) and data[key]:
                            users_list = data[key]
                            break

                if users_list:
                    user_data = parse_user(users_list[0])
                    # Include userProfiles for credential/app lookup
                    user_data['userProfiles'] = users_list[0].get('userProfiles', [])
                    send_json(self, {"user": user_data})
                    return

            send_json(self, {"error": "User not found"}, 404)

        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
