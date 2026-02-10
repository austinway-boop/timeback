"""GET /api/results — List results/grades (OneRoster gradebook)

Optional query params:
  ?userId=...   — filter by student sourcedId
  ?classId=...  — filter by class sourcedId
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import (
    fetch_all_paginated,
    fetch_with_params,
    send_json,
    get_query_params,
)


def parse_result(raw: dict) -> dict:
    """Normalise a OneRoster result record."""
    line_item = raw.get("lineItem", {}) or {}
    student = raw.get("student", {}) or {}

    return {
        "sourcedId": raw.get("sourcedId", ""),
        "lineItemSourcedId": line_item.get("sourcedId", ""),
        "studentSourcedId": student.get("sourcedId", ""),
        "score": raw.get("score", ""),
        "scoreStatus": raw.get("scoreStatus", ""),
        "scoreDate": raw.get("scoreDate", ""),
        "comment": raw.get("comment", ""),
        "status": raw.get("status", ""),
        "metadata": raw.get("metadata", {}),
    }


# OneRoster gradebook paths to try (in order of preference)
_RESULTS_PATHS = [
    "/ims/oneroster/gradebook/v1p2/results",
    "/ims/oneroster/v1p2/results",
]


def _fetch_results(filter_param: str | None = None) -> list:
    """Fetch results, trying multiple OneRoster paths.

    Attempts the gradebook path first, then falls back to the generic path.
    Optionally applies a OneRoster filter string.
    """
    for path in _RESULTS_PATHS:
        try:
            if filter_param:
                data, status = fetch_with_params(
                    path, {"filter": filter_param}
                )
                if data and status == 200:
                    results = data.get("results", [])
                    if not results:
                        for val in data.values():
                            if isinstance(val, list):
                                results = val
                                break
                    return results
            else:
                items = fetch_all_paginated(path, "results")
                if items:
                    return items
        except Exception:
            continue
    return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = get_query_params(self)
            user_id = params.get("userId", "")
            class_id = params.get("classId", "")

            # Build OneRoster filter
            filters = []
            if user_id:
                filters.append(f"studentSourcedId='{user_id}'")
            if class_id:
                filters.append(f"classSourcedId='{class_id}'")

            filter_param = " AND ".join(filters) if filters else None

            raw_results = _fetch_results(filter_param)
            results = [parse_result(r) for r in raw_results]

            # Client-side fallback filter (in case the API ignores filters)
            if user_id:
                results = [r for r in results if r["studentSourcedId"] == user_id]
            if class_id:
                results = [
                    r for r in results if r.get("classSourcedId") == class_id
                ]

            send_json(self, {"results": results, "count": len(results)})
        except Exception as e:
            send_json(self, {"error": str(e), "results": [], "count": 0}, 500)
