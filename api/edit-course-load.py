"""GET /api/edit-course-load?courseId=...

Loads the editable course structure. If a saved edit exists in KV, returns it.
Otherwise, fetches the PowerPath lesson plan tree (read-only) and transforms
it into our local edit format as the initial seed.

Uses the same multi-ID fallback strategy as find-course-tests:
  1. Try generic tree with original courseId
  2. Try with cached PP100 course ID
  3. Try with service user ID
"""

import time
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params
from api._kv import kv_get

SERVICE_USER_ID = "8ea2b8e1-1b04-4cab-b608-9ab524c059c2"


def _parse_resource(res_wrapper):
    """Parse a componentResource wrapper into (id, title, url, type)."""
    res = res_wrapper.get("resource", res_wrapper) if isinstance(res_wrapper, dict) else res_wrapper
    if not isinstance(res, dict):
        return None
    meta = res.get("metadata") or {}
    url = meta.get("url", "") or res.get("url", "") or meta.get("href", "") or res.get("href", "")
    res_id = res.get("id", "") or res.get("sourcedId", "") or ""
    res_title = res.get("title", "") or ""
    rtype = (meta.get("type", "") or res.get("type", "")).lower()
    return res_id, res_title, url, rtype


def _classify_type(rtype, url, title):
    """Classify a resource into video/article/quiz/other."""
    lower_url = (url or "").lower()
    lower_title = (title or "").lower()

    if rtype == "video":
        return "video"
    if rtype in ("quiz", "assessment", "test", "unit-test", "test-out", "placement"):
        return "quiz"
    if "stimuli" in lower_url:
        return "article"

    # Infer from title
    if "video" in lower_title:
        return "video"
    if "article" in lower_title or "reading" in lower_title:
        return "article"
    if "quiz" in lower_title or "assessment" in lower_title or "test" in lower_title:
        return "quiz"

    # Infer from URL
    if any(s in lower_url for s in ["youtube", "vimeo", ".mp4", ".webm"]):
        return "video"

    # Default: if it has a URL it's probably an assessment
    if url:
        return "quiz"

    return "other"


def _transform_tree(tree_data, course_id):
    """Transform a PowerPath lesson plan tree into our edit format.

    The tree is wrapped as: { lessonPlan: { subComponents: [ units ] } }
    Each unit has subComponents (lessons), each lesson has componentResources.
    """
    # Unwrap the tree — it may be nested under "lessonPlan"
    inner = tree_data
    if isinstance(inner, dict) and inner.get("lessonPlan"):
        inner = inner["lessonPlan"]
    if isinstance(inner, dict) and inner.get("lessonPlan"):
        inner = inner["lessonPlan"]

    # Get the units list
    if isinstance(inner, dict):
        unit_list = inner.get("subComponents", [])
    elif isinstance(inner, list):
        unit_list = inner
    else:
        unit_list = []

    units = []
    for u_idx, unit in enumerate(unit_list):
        if not isinstance(unit, dict):
            continue

        unit_id = unit.get("sourcedId") or unit.get("id") or f"unit-{u_idx}"
        unit_title = unit.get("title", f"Unit {u_idx + 1}")
        lesson_list = unit.get("subComponents", [])
        lessons = []

        for l_idx, lesson in enumerate(lesson_list):
            if not isinstance(lesson, dict):
                continue

            lesson_id = lesson.get("sourcedId") or lesson.get("id") or f"lesson-{u_idx}-{l_idx}"
            lesson_title = lesson.get("title", f"Lesson {l_idx + 1}")

            # Skip "Advanced Organizer Submission" items
            if "advanced organizer" in lesson_title.lower():
                continue

            activities = []
            for r_idx, res_wrap in enumerate(lesson.get("componentResources", [])):
                parsed = _parse_resource(res_wrap)
                if not parsed:
                    continue
                res_id, res_title, res_url, rtype = parsed
                act_type = _classify_type(rtype, res_url, res_title)

                activities.append({
                    "id": res_id or f"res-{u_idx}-{l_idx}-{r_idx}",
                    "type": act_type,
                    "title": res_title or lesson_title,
                    "sourceType": "powerpath",
                    "url": res_url,
                })

            lessons.append({
                "id": lesson_id,
                "title": lesson_title,
                "sortOrder": l_idx,
                "activities": activities,
            })

        # Also handle unit-level resources (unit tests) that aren't in lessons
        unit_resources = unit.get("componentResources", [])
        if unit_resources:
            unit_acts = []
            for r_idx, res_wrap in enumerate(unit_resources):
                parsed = _parse_resource(res_wrap)
                if not parsed:
                    continue
                res_id, res_title, res_url, rtype = parsed
                act_type = _classify_type(rtype, res_url, res_title)
                unit_acts.append({
                    "id": res_id or f"ures-{u_idx}-{r_idx}",
                    "type": act_type,
                    "title": res_title or unit_title,
                    "sourceType": "powerpath",
                    "url": res_url,
                })
            if unit_acts and not lessons:
                # If the unit has no lessons but has resources, create a pseudo-lesson
                lessons.append({
                    "id": f"unit-resources-{u_idx}",
                    "title": unit_title + " Resources",
                    "sortOrder": 0,
                    "activities": unit_acts,
                })

        units.append({
            "id": unit_id,
            "title": unit_title,
            "sortOrder": u_idx,
            "lessons": lessons,
        })

    return {
        "courseId": course_id,
        "lastModified": time.time(),
        "units": units,
        "isInitialSeed": True,
    }


def _try_tree(url, headers):
    """Try to fetch a tree from a URL. Returns parsed JSON or None."""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 401:
            headers = api_headers()
            resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data
    except Exception:
        pass
    return None


def _fetch_tree(course_id):
    """Fetch the PowerPath tree, trying multiple strategies.
    Returns (tree_data, debug_log) or (None, debug_log)."""
    debug = []
    headers = api_headers()

    # Build list of IDs to try: original + cached PP100
    ids_to_try = [course_id]
    cached_pp100 = kv_get(f"pp100_course_id:{course_id}")
    if cached_pp100 and cached_pp100 != course_id:
        ids_to_try.append(cached_pp100)
        debug.append(f"cached_pp100={cached_pp100}")

    # Strategy 1: Generic tree endpoint
    for cid in ids_to_try:
        tree = _try_tree(f"{API_BASE}/powerpath/lessonPlans/tree/{cid}", headers)
        if tree:
            debug.append(f"tree_generic: ok ({cid})")
            return tree, debug
    debug.append("tree_generic: all failed")

    # Strategy 2: User-specific endpoint with service account
    for cid in ids_to_try:
        tree = _try_tree(
            f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}", headers
        )
        if tree:
            debug.append(f"tree_user: ok ({cid})")
            return tree, debug
    debug.append("tree_user: all failed")

    return None, debug


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

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        # Check for saved edits in KV first
        saved = kv_get(f"course_edit:{course_id}")
        if saved and isinstance(saved, dict) and saved.get("units"):
            saved["isInitialSeed"] = False
            send_json(self, saved)
            return

        # No saved edits — fetch PowerPath tree as initial seed
        try:
            tree_data, debug = _fetch_tree(course_id)

            if not tree_data:
                send_json(self, {
                    "error": "Could not fetch course tree",
                    "courseId": course_id,
                    "units": [],
                    "_debug": debug,
                })
                return

            result = _transform_tree(tree_data, course_id)
            result["_debug"] = debug

            # If we got 0 units, include the raw tree keys so we can debug
            if not result.get("units"):
                raw_keys = list(tree_data.keys()) if isinstance(tree_data, dict) else f"type={type(tree_data).__name__}"
                inner = tree_data
                if isinstance(inner, dict) and inner.get("lessonPlan"):
                    inner = inner["lessonPlan"]
                inner_keys = list(inner.keys()) if isinstance(inner, dict) else f"type={type(inner).__name__}"
                result["_debug_tree_keys"] = raw_keys
                result["_debug_inner_keys"] = inner_keys

            send_json(self, result)

        except Exception as e:
            send_json(self, {"error": str(e), "units": []}, 500)
