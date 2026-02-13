"""GET /api/classes — List all classes (OneRoster)"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_all_paginated, send_json


def parse_class(raw: dict) -> dict:
    """Normalise a OneRoster class record."""
    # courseSourcedId lives in nested course.sourcedId
    course = raw.get("course", {}) or {}
    school = raw.get("school", {}) or {}

    return {
        "sourcedId": raw.get("sourcedId", ""),
        "title": raw.get("title", ""),
        "classCode": raw.get("classCode", ""),
        "classType": raw.get("classType", ""),
        "location": raw.get("location", ""),
        "courseSourcedId": course.get("sourcedId", ""),
        "schoolSourcedId": school.get("sourcedId", ""),
        "status": raw.get("status", ""),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            raw_classes = fetch_all_paginated(
                "/ims/oneroster/rostering/v1p2/classes", "classes"
            )
            classes = [parse_class(c) for c in raw_classes]
            send_json(self, {"classes": classes, "count": len(classes)})
        except Exception as e:
            send_json(self, {"error": str(e), "classes": [], "count": 0}, 500)
