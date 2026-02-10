"""GET /api/schools — List schools / organisations (OneRoster)"""

from http.server import BaseHTTPRequestHandler
from api._helpers import fetch_all_paginated, send_json


def parse_school(raw: dict) -> dict:
    """Normalise a OneRoster org/school record."""
    return {
        "sourcedId": raw.get("sourcedId", ""),
        "name": raw.get("name", ""),
        "type": raw.get("type", ""),
        "identifier": raw.get("identifier", ""),
        "status": raw.get("status", ""),
        "dateLastModified": raw.get("dateLastModified", ""),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # OneRoster may wrap under "orgs" or "schools"
            raw_schools = fetch_all_paginated(
                "/ims/oneroster/rostering/v1p2/schools", "orgs"
            )
            if not raw_schools:
                raw_schools = fetch_all_paginated(
                    "/ims/oneroster/rostering/v1p2/schools", "schools"
                )
            schools = [parse_school(s) for s in raw_schools]
            send_json(self, {"schools": schools, "count": len(schools)})
        except Exception as e:
            send_json(self, {"error": str(e), "schools": [], "count": 0}, 500)
