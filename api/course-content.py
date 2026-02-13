"""GET /api/course-content?courseId=...&userId=...

Fetches the lesson plan tree and student progress from the PowerPath API,
supplemented with direct OneRoster gradebook results.

Endpoints used:
  /powerpath/lessonPlans/tree/{courseId} — full tree (units → lessons → items)
  /powerpath/lessonPlans/{courseId}/{userId} — student-specific lesson plan
  /powerpath/lessonPlans/getCourseProgress/{courseId}/student/{userId} — progress
  /ims/oneroster/gradebook/v1p2/assessmentResults — direct gradebook results
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params

GRADEBOOK = f"{API_BASE}/ims/oneroster/gradebook/v1p2"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        course_id = params.get("courseId", "").strip()
        user_id = params.get("userId", "").strip()

        if not course_id:
            send_json(self, {"error": "Need courseId"}, 400)
            return

        result = {"lessonPlan": None, "courseProgress": None, "tree": None}

        try:
            headers = api_headers()

            # 1. Student-specific lesson plan (best: personalized + has completion status)
            if user_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/{course_id}/{user_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["lessonPlan"] = resp.json()
                except Exception:
                    pass

            # 2. Full lesson plan tree (fallback: structure without student-specific status)
            if not result["lessonPlan"]:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["tree"] = resp.json()
                except Exception:
                    pass

            # 3. Student progress (completion status for assessments)
            if user_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/getCourseProgress/{course_id}/student/{user_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["courseProgress"] = resp.json()
                except Exception:
                    pass

            # 4. Supplement with direct OneRoster assessment results
            # PowerPath's getCourseProgress may not include results written
            # directly to OneRoster via submit-result. Fetch them separately
            # and merge into courseProgress so the course page sees completions.
            if user_id and result.get("courseProgress"):
                try:
                    _merge_oneroster_results(
                        result["courseProgress"], user_id, headers
                    )
                except Exception:
                    pass

            result["success"] = True
            send_json(self, result)

        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
            send_json(self, result, 500)


def _merge_oneroster_results(course_progress, user_id, headers):
    """Fetch assessment results from OneRoster and merge missing ones
    into courseProgress lineItems so the course page sees them."""
    line_items = course_progress.get("lineItems") or []
    if not line_items:
        return

    # Build set of ALI UUIDs we care about
    ali_set = set()
    for item in line_items:
        ali = item.get("assessmentLineItemSourcedId", "")
        if ali:
            ali_set.add(ali)

    if not ali_set:
        return

    # Fetch all assessment results for this student from OneRoster
    try:
        resp = requests.get(
            f"{GRADEBOOK}/assessmentResults",
            headers=headers,
            params={"filter": f"student.sourcedId='{user_id}'"},
            timeout=15,
        )
        if resp.status_code != 200:
            return
        or_results = resp.json().get("assessmentResults", [])
    except Exception:
        return

    if not or_results:
        return

    # Build map: ALI sourcedId -> best result (prefer "fully graded")
    ali_to_result = {}
    for r in or_results:
        ali = (r.get("assessmentLineItem") or {}).get("sourcedId", "")
        if not ali or ali not in ali_set:
            continue
        existing = ali_to_result.get(ali)
        if not existing or r.get("scoreStatus") == "fully graded":
            ali_to_result[ali] = r

    if not ali_to_result:
        return

    # Merge into courseProgress lineItems
    for item in line_items:
        ali = item.get("assessmentLineItemSourcedId", "")
        if ali not in ali_to_result:
            continue

        or_result = ali_to_result[ali]
        or_id = or_result.get("sourcedId", "")

        # Check if this result is already in the lineItem
        existing_results = item.get("results") or []
        already_there = any(
            r.get("sourcedId") == or_id for r in existing_results
        )
        if already_there:
            continue

        # Add the OneRoster result to this lineItem
        if not item.get("results"):
            item["results"] = []
        item["results"].append({
            "sourcedId": or_id,
            "scoreStatus": or_result.get("scoreStatus", ""),
            "score": or_result.get("score"),
            "scoreDate": or_result.get("scoreDate", ""),
            "textScore": or_result.get("textScore", ""),
            "metadata": or_result.get("metadata"),
        })
