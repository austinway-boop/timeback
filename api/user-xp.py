"""GET /api/user-xp?userId=... — Aggregated XP / stats for a student.

Combines:
  - OneRoster results (XP from metadata)
  - EduBridge enrollments
  - EduBridge time-saved
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import (
    fetch_all_paginated,
    fetch_one,
    fetch_with_params,
    send_json,
    get_query_params,
)


# OneRoster gradebook paths to try
_RESULTS_PATHS = [
    "/ims/oneroster/gradebook/v1p2/results",
    "/ims/oneroster/v1p2/results",
]


def _fetch_user_results(user_id: str) -> list:
    """Fetch results for a specific student, trying multiple paths."""
    filter_param = f"studentSourcedId='{user_id}'"

    for path in _RESULTS_PATHS:
        try:
            data, status = fetch_with_params(path, {"filter": filter_param})
            if data and status == 200:
                results = data.get("results", [])
                if not results:
                    for val in data.values():
                        if isinstance(val, list):
                            results = val
                            break
                return results
        except Exception:
            continue

    # Fallback: fetch all results and filter client-side
    for path in _RESULTS_PATHS:
        try:
            all_results = fetch_all_paginated(path, "results")
            if all_results:
                return [
                    r
                    for r in all_results
                    if (r.get("student", {}) or {}).get("sourcedId") == user_id
                ]
        except Exception:
            continue

    return []


def _sum_xp(results: list) -> int:
    """Sum XP points from results metadata."""
    total = 0
    for r in results:
        meta = r.get("metadata", {}) or {}
        xp = meta.get("timeback.xp", 0)
        try:
            total += int(xp)
        except (ValueError, TypeError):
            pass
    return total


def _parse_result_summary(raw: dict) -> dict:
    """Slim result record for the XP response."""
    line_item = raw.get("lineItem", {}) or {}
    return {
        "sourcedId": raw.get("sourcedId", ""),
        "lineItemSourcedId": line_item.get("sourcedId", ""),
        "score": raw.get("score", ""),
        "scoreStatus": raw.get("scoreStatus", ""),
        "scoreDate": raw.get("scoreDate", ""),
        "metadata": raw.get("metadata", {}),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = get_query_params(self)
        user_id = params.get("userId", "")

        if not user_id:
            send_json(self, {"error": "Missing 'userId' query param"}, 400)
            return

        try:
            # 1. OneRoster results (XP)
            raw_results = _fetch_user_results(user_id)
            total_xp = _sum_xp(raw_results)
            results_summary = [_parse_result_summary(r) for r in raw_results]

            # 2. EduBridge enrollments
            enrollments_data, enr_status = fetch_one(
                f"/edubridge/enrollments/user/{user_id}"
            )
            enrollments = []
            if enrollments_data and enr_status == 200:
                # enrollments_data may be the full response or have an "enrollments" key
                if isinstance(enrollments_data, dict):
                    enrollments = enrollments_data.get(
                        "enrollments", enrollments_data.get("data", [])
                    )
                    if isinstance(enrollments, dict):
                        enrollments = [enrollments]
                elif isinstance(enrollments_data, list):
                    enrollments = enrollments_data

            # Sum XP earned from EduBridge enrollments
            enrollment_xp = 0
            for e in enrollments:
                try:
                    enrollment_xp += int(e.get("xpEarned", 0))
                except (ValueError, TypeError):
                    pass

            # Combined XP = OneRoster results XP + EduBridge enrollment XP
            combined_xp = total_xp + enrollment_xp

            # 3. EduBridge time saved
            time_data, ts_status = fetch_one(
                f"/edubridge/time-saved/user/{user_id}"
            )
            time_saved = time_data if time_data and ts_status == 200 else {}

            send_json(
                self,
                {
                    "userId": user_id,
                    "totalXP": combined_xp,
                    "enrollmentXP": enrollment_xp,
                    "resultsXP": total_xp,
                    "enrollments": enrollments,
                    "timeSaved": time_saved,
                    "results": results_summary,
                },
            )
        except Exception as e:
            send_json(
                self,
                {
                    "error": str(e),
                    "userId": user_id,
                    "totalXP": 0,
                    "enrollments": [],
                    "timeSaved": {},
                    "results": [],
                },
                500,
            )
