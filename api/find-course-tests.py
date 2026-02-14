"""POST /api/find-course-tests — Find all quiz/assessment resources for a course.

Receives { courseId, courseCode }.
Uses the PowerPath lesson plan tree (with enroll+sync if needed) to discover
all assessment resources. Falls back to OneRoster component resources.
Returns { tests: [{ id, title, url, lessonType, lessonTitle }, ...], count }.
"""

import json
import re
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import (
    API_BASE, CLIENT_ID, CLIENT_SECRET,
    api_headers, fetch_all_paginated, send_json, get_token,
)

# Staging/service account (pehal64861@aixind.com)
SERVICE_USER_ID = "8ea2b8e1-1b04-4cab-b608-9ab524c059c2"


# ── PowerPath tree: enroll + sync + fetch ────────────────────────────

def _find_pp100_course_ids(course_id: str) -> list[str]:
    """Find PP100 course IDs that correspond to the given course.
    Searches for courses with 'PP100' in the title matching the same subject."""
    try:
        # Get the original course's title to match against
        from api._helpers import fetch_one
        course_data, status = fetch_one(f"/ims/oneroster/rostering/v1p2/courses/{course_id}")
        if not course_data:
            return []
        course_obj = course_data.get("course", course_data)
        original_title = (course_obj.get("title") or "").lower()

        # Extract key subject words from the title (keep short words like "us", "ap")
        stop_words = {"the", "and", "for", "with", "a", "an", "in", "of", "to"}
        keywords = []
        for word in original_title.replace("-", " ").replace(":", " ").split():
            word = word.strip()
            if word and word not in stop_words:
                keywords.append(word)

        # Also extract from course code (e.g., "APUSH" → "apush")
        course_code_lower = (course_obj.get("courseCode") or "").lower().strip()
        if course_code_lower:
            keywords.append(course_code_lower)

        # Build subject fingerprint: expand abbreviations
        expanded = original_title
        for abbr, full in [("us ", "united states "), ("u.s. ", "united states "), ("govt", "government"), ("gov ", "government ")]:
            expanded = expanded.replace(abbr, full)

        # Fetch all courses and find PP100 versions
        all_courses = fetch_all_paginated(
            "/ims/oneroster/rostering/v1p2/courses", "courses"
        )
        pp100_ids = []
        for c in all_courses:
            cid = c.get("sourcedId", "")
            title = (c.get("title") or "").lower()
            if cid == course_id:
                continue
            if "pp100" not in title and "pp100" not in cid.lower():
                continue
            # Check if this PP100 course matches the subject
            # Match on: any keyword from title, expanded title match, or code substring
            match_count = sum(1 for kw in keywords if kw in title)
            # Also check if expanded title shares words
            for word in expanded.replace("-", " ").split():
                if len(word) >= 4 and word in title:
                    match_count += 1
            if match_count >= 1:  # At least 1 keyword match
                pp100_ids.append(cid)

        return pp100_ids
    except Exception:
        return []


def _get_powerpath_tree(course_id: str) -> tuple[dict | None, list]:
    """Get the PowerPath lesson plan tree, enrolling + syncing if needed.
    Also searches for PP100 course versions if the original ID fails.
    Returns (tree_data, debug_log)."""
    debug = []
    headers = api_headers()

    # Build list of IDs to try: original + PP100 versions
    ids_to_try = [course_id]
    pp100_ids = _find_pp100_course_ids(course_id)
    for pid in pp100_ids:
        if pid not in ids_to_try:
            ids_to_try.append(pid)
    debug.append(f"ids_to_try={ids_to_try}")

    # Step 1: Try generic tree endpoint for each ID
    for cid in ids_to_try:
        tree = _try_tree(f"{API_BASE}/powerpath/lessonPlans/tree/{cid}", headers)
        if tree:
            debug.append(f"tree_generic: ok ({cid})")
            return tree, debug
    debug.append("tree_generic: all failed")

    # Step 2: Try with service user ID for each
    for cid in ids_to_try:
        tree = _try_tree(f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}", headers)
        if tree:
            debug.append(f"tree_user: ok ({cid})")
            return tree, debug
    debug.append("tree_user: all failed")

    # Step 3: Enroll + sync for each ID, then retry
    for cid in ids_to_try:
        _enroll_service_account(cid, headers)
        _sync_course(cid, headers)
        debug.append(f"enrolled+synced: {cid}")

        headers = api_headers()  # refresh token
        tree = _try_tree(f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}", headers)
        if tree:
            debug.append(f"tree_after_sync: ok ({cid})")
            return tree, debug

    debug.append("tree_after_sync: all failed")
    return None, debug


def _try_tree(url: str, headers: dict) -> dict | None:
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


def _enroll_service_account(course_id: str, headers: dict):
    """Enroll the service account in a course via EduBridge."""
    try:
        requests.post(
            f"{API_BASE}/edubridge/enrollments/enroll/{SERVICE_USER_ID}/{course_id}",
            headers=headers,
            json={"role": "student"},
            timeout=15,
        )
    except Exception:
        pass


def _sync_course(course_id: str, headers: dict):
    """Trigger PowerPath to provision lesson plans for the course."""
    try:
        resp = requests.post(
            f"{API_BASE}/powerpath/lessonPlans/course/{course_id}/sync",
            headers=headers,
            json={},
            timeout=60,
        )
        if resp.status_code == 401:
            headers = api_headers()
            requests.post(
                f"{API_BASE}/powerpath/lessonPlans/course/{course_id}/sync",
                headers=headers,
                json={},
                timeout=60,
            )
    except Exception:
        pass


# ── Extract assessments from tree ────────────────────────────────────

def _extract_assessments_from_tree(tree: dict) -> list[dict]:
    """Walk the PowerPath tree and extract all assessment resources."""
    tests = []

    # Navigate to the actual tree data
    inner = tree.get("lessonPlan", tree) if isinstance(tree, dict) else tree
    if isinstance(inner, dict) and inner.get("lessonPlan"):
        inner = inner["lessonPlan"]

    units = inner.get("subComponents", []) if isinstance(inner, dict) else []
    if isinstance(inner, list):
        units = inner

    for unit in units:
        if not isinstance(unit, dict):
            continue
        unit_title = unit.get("title", "")
        lessons = unit.get("subComponents", [])

        # Handle unit-level resources (e.g., unit tests)
        unit_resources = unit.get("componentResources", [])
        if not lessons and unit_resources:
            for ur in unit_resources:
                _extract_resource(ur, unit_title, unit_title, tests)

        for lesson in lessons:
            if not isinstance(lesson, dict):
                continue
            lesson_title = lesson.get("title", "")

            for res_wrapper in lesson.get("componentResources", []):
                _extract_resource(res_wrapper, lesson_title, unit_title, tests)

    return tests


def _extract_resource(res_wrapper: dict, lesson_title: str, unit_title: str, tests: list):
    """Extract a single resource if it's an assessment type."""
    res = res_wrapper.get("resource", res_wrapper) if isinstance(res_wrapper, dict) else res_wrapper
    if not isinstance(res, dict):
        return

    meta = res.get("metadata") or {}
    rurl = meta.get("url", "") or res.get("url", "") or meta.get("href", "") or res.get("href", "")
    res_id = res.get("id", "") or res.get("sourcedId", "") or ""
    res_title = res.get("title", "") or lesson_title
    rtype = (meta.get("type", "") or res.get("type", "")).lower()

    # Skip videos and articles/stimuli
    if rtype == "video":
        return
    if rurl and "stimuli" in rurl.lower():
        return

    # This is an assessment resource
    if res_id or rurl:
        if not any(t["id"] == res_id for t in tests):
            tests.append({
                "id": res_id,
                "title": res_title,
                "url": rurl,
                "unitTitle": unit_title,
                "lessonTitle": lesson_title,
                "lessonType": rtype or "assessment",
            })


# ── Fallback: OneRoster component resources ──────────────────────────

QUIZ_LESSON_TYPES = {"quiz", "unit-test", "test-out", "placement", "powerpath-100"}


def _try_oneroster_components(course_id: str) -> list[dict]:
    """Fallback: fetch quiz resources via OneRoster component resources."""
    tests = []
    try:
        components = fetch_all_paginated(
            f"/ims/oneroster/rostering/v1p2/courses/components?filter=course.sourcedId%3D'{course_id}'",
            "courseComponents",
        )
        if not components:
            return []

        component_ids = set()
        for comp in components:
            cid = comp.get("sourcedId") or comp.get("id") or ""
            if cid:
                component_ids.add(cid)
            for cr in comp.get("componentResources", []):
                _extract_oneroster_resource(cr, tests)

        # Also try bulk fetch of component resources
        all_cr = fetch_all_paginated(
            "/ims/oneroster/rostering/v1p2/courses/component-resources",
            "componentResources",
        )
        for cr in all_cr:
            cc = cr.get("courseComponent") or {}
            if cc.get("sourcedId", "") in component_ids:
                _extract_oneroster_resource(cr, tests)

    except Exception:
        pass
    return tests


def _extract_oneroster_resource(cr: dict, tests: list):
    """Extract a test from an OneRoster component resource."""
    lesson_type = (cr.get("lessonType") or "").lower().strip()
    title = cr.get("title") or ""
    cr_id = cr.get("sourcedId") or cr.get("id") or ""
    resource = cr.get("resource") or {}
    resource_id = resource.get("sourcedId") or resource.get("id") or ""
    component = cr.get("courseComponent") or {}
    component_id = component.get("sourcedId") or ""
    dedup_id = cr_id or resource_id

    is_quiz = lesson_type in QUIZ_LESSON_TYPES
    if dedup_id and is_quiz:
        if not any(t["id"] == dedup_id for t in tests):
            tests.append({
                "id": dedup_id,
                "resourceId": resource_id,
                "componentId": component_id,
                "title": title or dedup_id,
                "lessonType": lesson_type,
            })


# ── Handler ──────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        course_id = body.get("courseId", "").strip()
        course_code = body.get("courseCode", "").strip()

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        all_tests = []
        sources = []
        debug_log = []

        # Tier 1: PowerPath lesson plan tree (enroll + sync if needed)
        tree, tree_debug = _get_powerpath_tree(course_id)
        debug_log.extend(tree_debug)

        if tree:
            pp_tests = _extract_assessments_from_tree(tree)
            debug_log.append(f"pp_tests_count={len(pp_tests)}")
            for t in pp_tests:
                if not any(x["id"] == t["id"] for x in all_tests):
                    all_tests.append(t)
            if pp_tests:
                sources.append("powerpath_tree")

        # Tier 2: OneRoster component resources (fallback)
        if not all_tests:
            or_tests = _try_oneroster_components(course_id)
            for t in or_tests:
                if not any(x["id"] == t["id"] for x in all_tests):
                    all_tests.append(t)
            if or_tests:
                sources.append("oneroster_components")

        send_json(self, {
            "tests": all_tests,
            "count": len(all_tests),
            "sources": sources,
            "_debug": debug_log,
        })
