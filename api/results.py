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
    """Normalise a OneRoster result record.
    
    Handles both regular results (lineItem) and assessment results (assessmentLineItem).
    """
    # Handle both lineItem and assessmentLineItem formats
    line_item = raw.get("lineItem", {}) or raw.get("assessmentLineItem", {}) or {}
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
# Include BOTH assessmentResults (gradebook API) and results (rostering API)
_RESULTS_PATHS = [
    "/ims/oneroster/gradebook/v1p2/assessmentResults",  # This is where submit-result.py writes!
    "/ims/oneroster/gradebook/v1p2/results",
    "/ims/oneroster/v1p2/results",
]


def _fetch_results(filter_param: str | None = None, is_assessment: bool = False) -> list:
    """Fetch results, trying multiple OneRoster paths.

    Attempts the gradebook path first, then falls back to the generic path.
    Optionally applies a OneRoster filter string.
    
    Args:
        filter_param: OneRoster filter string
        is_assessment: If True, query assessmentResults paths first
    """
    # Reorder paths based on whether we expect assessment results
    paths = _RESULTS_PATHS if is_assessment else _RESULTS_PATHS[::-1]
    
    all_results = []
    
    for path in _RESULTS_PATHS:
        # Determine the collection key based on path
        if "assessmentResults" in path:
            collection_key = "assessmentResults"
        else:
            collection_key = "results"
            
        try:
            if filter_param:
                data, status = fetch_with_params(
                    path, {"filter": filter_param}
                )
                if data and status == 200:
                    results = data.get(collection_key, []) or data.get("results", [])
                    if not results:
                        for val in data.values():
                            if isinstance(val, list):
                                results = val
                                break
                    if results:
                        all_results.extend(results)
            else:
                items = fetch_all_paginated(path, collection_key)
                if not items:
                    # Try alternate key
                    items = fetch_all_paginated(path, "results")
                if items:
                    all_results.extend(items)
        except Exception:
            continue
    
    # Deduplicate by sourcedId
    seen = set()
    unique_results = []
    for r in all_results:
        sid = r.get("sourcedId", "")
        if sid and sid not in seen:
            seen.add(sid)
            unique_results.append(r)
        elif not sid:
            unique_results.append(r)
    
    return unique_results


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = get_query_params(self)
            user_id = params.get("userId", "")
            class_id = params.get("classId", "")

            # Build OneRoster filter
            # Note: gradebook API uses nested format (student.sourcedId)
            # while rostering API uses flat format (studentSourcedId)
            filters = []
            if user_id:
                # Use nested format for gradebook assessmentResults
                filters.append(f"student.sourcedId='{user_id}'")
            if class_id:
                filters.append(f"class.sourcedId='{class_id}'")

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
