"""POST /api/find-course-tests — Find all QTI assessment tests for a course.

Receives { courseId, courseCode }.
Searches the QTI assessment-tests catalog for tests matching the course code.
Also tries the PowerPath tree for resource IDs as a secondary source.
Returns { tests: [{ id, title }, ...], count }.
"""

import json
import re
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import API_BASE, CLIENT_ID, CLIENT_SECRET, api_headers, send_json, get_token

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"


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


def _fetch_qti_catalog(token: str) -> list[dict]:
    """Fetch all assessment tests from QTI catalog."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    tests = []
    try:
        resp = requests.get(
            f"{QTI_BASE}/api/assessment-tests?limit=100",
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            tests.extend(data.get("items", []))
            # Handle pagination if available
            total_pages = data.get("pages", 1)
            for page in range(2, min(total_pages + 1, 11)):  # Max 10 pages
                resp2 = requests.get(
                    f"{QTI_BASE}/api/assessment-tests?limit=100&page={page}",
                    headers=headers,
                    timeout=30,
                )
                if resp2.status_code == 200:
                    tests.extend(resp2.json().get("items", []))
    except Exception:
        pass
    return tests


def _filter_tests_by_code(tests: list[dict], course_code: str) -> list[dict]:
    """Filter QTI tests that match the course code."""
    if not course_code:
        return []
    code_lower = course_code.lower()
    # Also try just the alpha prefix (e.g., "USHI" from "USHI23")
    alpha_prefix = re.match(r'^[a-zA-Z]+', course_code)
    prefix = alpha_prefix.group(0).lower() if alpha_prefix else ""

    matched = []
    for test in tests:
        tid = (test.get("identifier") or test.get("id") or "").lower()
        title = (test.get("title") or test.get("name") or "").lower()
        # Match by course code in ID or title
        if code_lower in tid or code_lower in title:
            matched.append(test)
        elif prefix and len(prefix) >= 3 and (prefix in tid or prefix in title):
            matched.append(test)
    return matched


def _try_powerpath_tree(course_id: str) -> list[dict]:
    """Try to get quiz resource IDs from PowerPath lesson plan tree."""
    try:
        headers = api_headers()
        resp = requests.get(
            f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}",
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        tree = resp.json()
        resources = []

        def walk(node):
            if isinstance(node, dict):
                # Check if this is a quiz/assessment resource
                res_type = (node.get("type") or node.get("nodeType") or "").lower()
                res_id = node.get("sourcedId") or node.get("id") or ""
                title = node.get("title") or node.get("name") or ""
                if res_id and ("assessment" in res_type or "quiz" in res_type or "test" in res_type or "bank" in res_id.lower()):
                    resources.append({"id": res_id, "title": title})
                # Also check componentResources
                comp_res = node.get("componentResources") or []
                for cr in comp_res:
                    r = cr.get("resource", cr) if isinstance(cr, dict) else {}
                    r_type = (r.get("type") or "").lower()
                    r_id = r.get("sourcedId") or r.get("id") or ""
                    r_title = r.get("title") or ""
                    r_url = r.get("url") or (r.get("metadata") or {}).get("url", "")
                    if r_id and ("assessment" in r_type or "bank" in r_id.lower() or "assessment" in r_url):
                        resources.append({"id": r_id, "title": r_title})
                # Recurse
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

        # Source 1: QTI catalog search
        if course_code:
            try:
                token = _get_qti_token()
                catalog = _fetch_qti_catalog(token)
                matched = _filter_tests_by_code(catalog, course_code)
                for t in matched:
                    tid = t.get("identifier") or t.get("id") or ""
                    title = t.get("title") or t.get("name") or ""
                    if tid and not any(x["id"] == tid for x in all_tests):
                        all_tests.append({"id": tid, "title": title})
                if matched:
                    sources.append("qti_catalog")
            except Exception:
                pass

        # Source 2: PowerPath tree resource IDs
        pp_resources = _try_powerpath_tree(course_id)
        for r in pp_resources:
            rid = r["id"]
            if not any(x["id"] == rid for x in all_tests):
                all_tests.append(r)
        if pp_resources:
            sources.append("powerpath_tree")

        send_json(self, {
            "tests": all_tests,
            "count": len(all_tests),
            "sources": sources,
        })
