"""GET /api/lesson-count?userId=...&startDate=...&endDate=...

Counts actual completed lessons (quizzes, FRQs, tests) per course for a student
in a date range. Uses assessment results API and filters out individual questions
to only count real lesson completions.

Returns: { "courses": { "courseSourcedId": lessonCount, ... } }
"""

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

import requests

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
CLIENT_ID = os.environ.get("TIMEBACK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TIMEBACK_CLIENT_SECRET", "")
API_BASE = "https://api.alpha-1edtech.ai"


def _get_token():
    resp = requests.post(
        COGNITO_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _send_json(handler, data, status=200):
    body = json.dumps(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body.encode())


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        user_id = params.get("userId", "")
        start_date = params.get("startDate", "")
        end_date = params.get("endDate", "")

        if not user_id:
            _send_json(self, {"error": "Missing userId"}, 400)
            return

        try:
            token = _get_token()
            headers = {"Authorization": f"Bearer {token}"}

            # Fetch assessment results for the student (paginated)
            all_results = []
            offset = 0
            while True:
                resp = requests.get(
                    f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentResults",
                    headers=headers,
                    params={
                        "filter": f"student.sourcedId='{user_id}'",
                        "limit": 100,
                        "offset": offset,
                        "sort": "dateLastModified",
                        "orderBy": "desc",
                    },
                    timeout=30,
                )
                if resp.status_code == 401:
                    token = _get_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    resp = requests.get(
                        f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentResults",
                        headers=headers,
                        params={
                            "filter": f"student.sourcedId='{user_id}'",
                            "limit": 100,
                            "offset": offset,
                            "sort": "dateLastModified",
                            "orderBy": "desc",
                        },
                        timeout=30,
                    )

                data = resp.json() if resp.status_code == 200 else {}
                results = data.get("assessmentResults", [])
                if not results:
                    for v in data.values():
                        if isinstance(v, list):
                            results = v
                            break

                # Filter by date range
                filtered = []
                any_in_range = False
                for r in results:
                    sd = r.get("scoreDate", "")
                    if start_date and sd < start_date:
                        continue
                    if end_date and sd > end_date:
                        continue
                    any_in_range = True
                    filtered.append(r)
                all_results.extend(filtered)

                # Stop if we've gone past the date range or no more results
                if len(results) < 100:
                    break
                # If none in range and results are older, stop
                if results and not any_in_range:
                    oldest = results[-1].get("scoreDate", "")
                    if oldest and start_date and oldest < start_date:
                        break
                offset += 100

            # Collect unique line item IDs per course (graded only)
            li_ids_by_course = defaultdict(set)
            for ar in all_results:
                if ar.get("scoreStatus") != "fully graded":
                    continue
                meta = ar.get("metadata", {}) or {}
                course = meta.get("courseSourcedId", "")
                if not course:
                    continue
                li = ar.get("assessmentLineItem", {}) or {}
                li_id = li.get("sourcedId", "") if isinstance(li, dict) else ""
                if li_id:
                    li_ids_by_course[course].add(li_id)

            # Look up line item titles and count lessons (not individual questions)
            courses = {}
            for course_id, li_ids in li_ids_by_course.items():
                lesson_count = 0
                for li_id in li_ids:
                    try:
                        r = requests.get(
                            f"{API_BASE}/ims/oneroster/gradebook/v1p2/assessmentLineItems/{li_id}",
                            headers=headers,
                            timeout=10,
                        )
                        if r.status_code == 200:
                            li_data = r.json()
                            li_obj = li_data.get("assessmentLineItem", li_data)
                            title = li_obj.get("title", "")
                            # Lessons are Tests/FRQs/Quizzes — NOT individual "Question:" items
                            if "Question:" not in title and title:
                                lesson_count += 1
                    except Exception:
                        continue
                courses[course_id] = lesson_count

            _send_json(self, {"courses": courses})

        except Exception as e:
            _send_json(self, {"error": str(e), "courses": {}}, 500)
