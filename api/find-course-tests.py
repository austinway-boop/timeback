"""POST /api/find-course-tests — Find all QTI assessment tests for a course.

Receives { courseId, courseCode }.
Uses a 3-tier approach to discover test/quiz resource IDs:
  1. OneRoster course components → component resources (most reliable)
  2. QTI catalog search by course code
  3. PowerPath lesson plan tree
Returns { tests: [{ id, title, lessonType }, ...], count }.
"""

import json
import re
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import (
    API_BASE, CLIENT_ID, CLIENT_SECRET,
    api_headers, fetch_all_paginated, send_json, get_token,
)

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"

# lessonType values that indicate quiz/assessment content
QUIZ_LESSON_TYPES = {"quiz", "unit-test", "test-out", "placement", "powerpath-100"}


# ── Tier 1: OneRoster Course Components → Component Resources ─────────

def _try_oneroster_components(course_id: str) -> list[dict]:
    """Fetch quiz resource IDs via OneRoster course components and component resources."""
    tests = []
    try:
        # Step 1: Get all course components
        components = fetch_all_paginated(
            f"/ims/oneroster/rostering/v1p2/courses/components?filter=course.sourcedId%3D'{course_id}'",
            "courseComponents",
        )
        if not components:
            return []

        component_ids = []
        for comp in components:
            cid = comp.get("sourcedId") or comp.get("id") or ""
            if cid:
                component_ids.append(cid)

            # Some component responses embed componentResources directly
            embedded_resources = comp.get("componentResources") or []
            for cr in embedded_resources:
                _extract_test_from_resource(cr, tests)

        if tests:
            return tests

        # Step 2: Fetch component resources for all components
        # Try bulk fetch first (all component resources for the course)
        all_comp_resources = fetch_all_paginated(
            "/ims/oneroster/rostering/v1p2/courses/component-resources",
            "componentResources",
        )
        if all_comp_resources:
            # Filter to only those belonging to our course's components
            comp_id_set = set(component_ids)
            for cr in all_comp_resources:
                cc = cr.get("courseComponent") or {}
                cc_id = cc.get("sourcedId") or ""
                if cc_id in comp_id_set:
                    _extract_test_from_resource(cr, tests)

        if tests:
            return tests

        # Step 3: Try fetching component resources per-component (slower but more targeted)
        for cid in component_ids[:50]:  # Cap at 50 to avoid timeout
            try:
                comp_resources = fetch_all_paginated(
                    f"/ims/oneroster/rostering/v1p2/courses/component-resources?filter=courseComponent.sourcedId%3D'{cid}'",
                    "componentResources",
                )
                for cr in comp_resources:
                    _extract_test_from_resource(cr, tests)
            except Exception:
                continue

    except Exception:
        pass
    return tests


def _extract_test_from_resource(cr: dict, tests: list):
    """Extract a test entry from a component resource if it's a quiz/assessment type."""
    lesson_type = (cr.get("lessonType") or "").lower().strip()
    title = cr.get("title") or ""
    resource = cr.get("resource") or {}
    res_id = resource.get("sourcedId") or resource.get("id") or cr.get("sourcedId") or ""

    # Include if lessonType indicates a quiz, OR if the resource ID looks like a bank/assessment
    is_quiz_type = lesson_type in QUIZ_LESSON_TYPES
    is_bank_id = res_id and ("bank" in res_id.lower() or "test" in res_id.lower() or "qti" in res_id.lower())

    if res_id and (is_quiz_type or is_bank_id):
        if not any(t["id"] == res_id for t in tests):
            tests.append({
                "id": res_id,
                "title": title or res_id,
                "lessonType": lesson_type or "unknown",
            })


# ── Tier 2: QTI Catalog Search ───────────────────────────────────────

def _get_qti_token():
    """Get Cognito token with QTI admin scope."""
    try:
        resp = requests.post(
            COGNITO_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope": "qti/v3/scope/admin",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()["access_token"]
    except Exception:
        pass
    return get_token()


def _try_qti_catalog(course_code: str) -> list[dict]:
    """Search QTI catalog for assessment tests matching the course code."""
    if not course_code:
        return []
    tests = []
    try:
        token = _get_qti_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        resp = requests.get(f"{QTI_BASE}/api/assessment-tests?limit=100", headers=headers, timeout=30)
        if resp.status_code != 200:
            return []

        catalog = resp.json().get("items", [])

        # Handle pagination
        total_pages = resp.json().get("pages", 1)
        for page in range(2, min(total_pages + 1, 11)):
            resp2 = requests.get(f"{QTI_BASE}/api/assessment-tests?limit=100&page={page}", headers=headers, timeout=30)
            if resp2.status_code == 200:
                catalog.extend(resp2.json().get("items", []))

        code_lower = course_code.lower()
        alpha_prefix = re.match(r'^[a-zA-Z]+', course_code)
        prefix = alpha_prefix.group(0).lower() if alpha_prefix else ""

        for item in catalog:
            tid = (item.get("identifier") or item.get("id") or "").lower()
            title = (item.get("title") or item.get("name") or "").lower()
            if code_lower in tid or code_lower in title:
                tests.append(item)
            elif prefix and len(prefix) >= 3 and (prefix in tid or prefix in title):
                tests.append(item)

    except Exception:
        pass
    return [{"id": t.get("identifier") or t.get("id") or "", "title": t.get("title") or t.get("name") or ""} for t in tests]


# ── Tier 3: PowerPath Tree ───────────────────────────────────────────

def _try_powerpath_tree(course_id: str) -> list[dict]:
    """Try to get quiz resource IDs from PowerPath lesson plan tree."""
    try:
        headers = api_headers()
        resp = requests.get(f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}", headers=headers, timeout=30)
        if resp.status_code != 200:
            return []
        tree = resp.json()
        resources = []

        def walk(node):
            if isinstance(node, dict):
                res_type = (node.get("type") or node.get("nodeType") or "").lower()
                res_id = node.get("sourcedId") or node.get("id") or ""
                title = node.get("title") or node.get("name") or ""
                if res_id and ("assessment" in res_type or "quiz" in res_type or "bank" in res_id.lower()):
                    resources.append({"id": res_id, "title": title})
                comp_res = node.get("componentResources") or []
                for cr in comp_res:
                    r = cr.get("resource", cr) if isinstance(cr, dict) else {}
                    r_id = r.get("sourcedId") or r.get("id") or ""
                    r_title = r.get("title") or ""
                    if r_id and ("bank" in r_id.lower() or "assessment" in (r.get("type") or "").lower()):
                        resources.append({"id": r_id, "title": r_title})
                for key in ("children", "lessons", "items", "units"):
                    children = node.get(key, [])
                    if isinstance(children, list):
                        for child in children:
                            walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(tree)
        return resources
    except Exception:
        return []


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

        # Tier 1: OneRoster course components → component resources (most reliable)
        or_tests = _try_oneroster_components(course_id)
        for t in or_tests:
            if not any(x["id"] == t["id"] for x in all_tests):
                all_tests.append(t)
        if or_tests:
            sources.append("oneroster_components")

        # Tier 2: QTI catalog search (if Tier 1 found nothing)
        if not all_tests and course_code:
            qti_tests = _try_qti_catalog(course_code)
            for t in qti_tests:
                if t["id"] and not any(x["id"] == t["id"] for x in all_tests):
                    all_tests.append(t)
            if qti_tests:
                sources.append("qti_catalog")

        # Tier 3: PowerPath tree (if still nothing)
        if not all_tests:
            pp_tests = _try_powerpath_tree(course_id)
            for t in pp_tests:
                if not any(x["id"] == t["id"] for x in all_tests):
                    all_tests.append(t)
            if pp_tests:
                sources.append("powerpath_tree")

        send_json(self, {
            "tests": all_tests,
            "count": len(all_tests),
            "sources": sources,
        })
