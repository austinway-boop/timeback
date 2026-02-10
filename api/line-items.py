"""GET /api/line-items — List line items / assignments / tests (OneRoster gradebook)

Optional query params:
  ?classId=... — filter by class sourcedId
"""

from http.server import BaseHTTPRequestHandler
from api._helpers import (
    fetch_all_paginated,
    fetch_with_params,
    send_json,
    get_query_params,
)


def parse_line_item(raw: dict) -> dict:
    """Normalise a OneRoster lineItem record."""
    class_ref = raw.get("class", {}) or {}
    category = raw.get("category", {}) or {}

    return {
        "sourcedId": raw.get("sourcedId", ""),
        "title": raw.get("title", ""),
        "description": raw.get("description", ""),
        "classSourcedId": class_ref.get("sourcedId", ""),
        "categorySourcedId": category.get("sourcedId", ""),
        "assignDate": raw.get("assignDate", ""),
        "dueDate": raw.get("dueDate", ""),
        "resultValueMin": raw.get("resultValueMin", ""),
        "resultValueMax": raw.get("resultValueMax", ""),
        "status": raw.get("status", ""),
    }


# OneRoster gradebook paths to try
_LINE_ITEMS_PATHS = [
    "/ims/oneroster/gradebook/v1p2/lineItems",
    "/ims/oneroster/v1p2/lineItems",
]


def _fetch_line_items(filter_param: str | None = None) -> list:
    """Fetch line items, trying multiple OneRoster paths."""
    for path in _LINE_ITEMS_PATHS:
        try:
            if filter_param:
                data, status = fetch_with_params(
                    path, {"filter": filter_param}
                )
                if data and status == 200:
                    items = data.get("lineItems", [])
                    if not items:
                        for val in data.values():
                            if isinstance(val, list):
                                items = val
                                break
                    return items
            else:
                items = fetch_all_paginated(path, "lineItems")
                if items:
                    return items
        except Exception:
            continue
    return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = get_query_params(self)
            class_id = params.get("classId", "")

            filter_param = f"classSourcedId='{class_id}'" if class_id else None

            raw_items = _fetch_line_items(filter_param)
            line_items = [parse_line_item(li) for li in raw_items]

            # Client-side fallback filter
            if class_id:
                line_items = [
                    li for li in line_items if li["classSourcedId"] == class_id
                ]

            send_json(self, {"lineItems": line_items, "count": len(line_items)})
        except Exception as e:
            send_json(
                self, {"error": str(e), "lineItems": [], "count": 0}, 500
            )
