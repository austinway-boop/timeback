"""GET /api/results — List results/grades (OneRoster gradebook)

Optional query params:
  ?userId=...   — filter by student sourcedId
  ?classId=...  — filter by class sourcedId
  ?limit=...    — max results per endpoint (default 100)
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import (
    API_BASE,
    api_headers,
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
# Only include paths that actually work
_RESULTS_PATHS = [
    ("/ims/oneroster/gradebook/v1p2/assessmentResults", "assessmentResults"),
    ("/ims/oneroster/gradebook/v1p2/results", "results"),
]


def _fetch_results_single_page(path: str, collection_key: str, params: dict, limit: int = 100) -> list:
    """Fetch a single page of results from a OneRoster endpoint."""
    headers = api_headers()
    url = f"{API_BASE}{path}"
    
    query_params = {"limit": limit}
    if params.get("filter"):
        query_params["filter"] = params["filter"]
    
    try:
        resp = requests.get(url, headers=headers, params=query_params, timeout=30)
        if resp.status_code == 401:
            headers = api_headers()
            resp = requests.get(url, headers=headers, params=query_params, timeout=30)
        
        if resp.status_code != 200:
            return []
        
        data = resp.json()
        results = data.get(collection_key, [])
        if not results:
            # Try alternate keys
            for key in ["results", "assessmentResults"]:
                if key in data and isinstance(data[key], list):
                    results = data[key]
                    break
            if not results:
                for val in data.values():
                    if isinstance(val, list):
                        results = val
                        break
        return results
    except Exception:
        return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = get_query_params(self)
            user_id = params.get("userId", "")
            class_id = params.get("classId", "")
            limit = int(params.get("limit", "100"))

            # Build OneRoster filter
            # Note: gradebook API uses nested format (student.sourcedId)
            filters = []
            if user_id:
                filters.append(f"student.sourcedId='{user_id}'")
            if class_id:
                filters.append(f"class.sourcedId='{class_id}'")

            filter_param = " AND ".join(filters) if filters else None
            fetch_params = {"filter": filter_param} if filter_param else {}
            
            all_results = []
            
            # Fetch from both endpoints
            for path, collection_key in _RESULTS_PATHS:
                items = _fetch_results_single_page(path, collection_key, fetch_params, limit)
                if items:
                    all_results.extend(items)
            
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
            
            results = [parse_result(r) for r in unique_results]

            # Client-side fallback filter (in case the API ignores filters)
            if user_id:
                results = [r for r in results if r["studentSourcedId"] == user_id]
            if class_id:
                results = [r for r in results if r.get("classSourcedId") == class_id]

            send_json(self, {"results": results, "count": len(results)})
        except Exception as e:
            send_json(self, {"error": str(e), "results": [], "count": 0}, 500)
