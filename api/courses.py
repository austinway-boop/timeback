"""GET /api/courses — List all courses (OneRoster)"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_all_paginated, send_json


def parse_course(raw: dict) -> dict:
    """Normalise a OneRoster course record."""
    return {
        "sourcedId": raw.get("sourcedId", ""),
        "title": raw.get("title", ""),
        "courseCode": raw.get("courseCode", ""),
        "status": raw.get("status", ""),
        "dateLastModified": raw.get("dateLastModified", ""),
        "metadata": raw.get("metadata", {}),
        "subjects": raw.get("subjects", []),
        "grades": raw.get("grades", []),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            raw_courses = fetch_all_paginated(
                "/ims/oneroster/rostering/v1p2/courses", "courses"
            )
            courses = [parse_course(c) for c in raw_courses]
            send_json(self, {"courses": courses, "count": len(courses)})
        except Exception as e:
            send_json(self, {"error": str(e), "courses": [], "count": 0}, 500)
