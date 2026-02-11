"""GET /api/qti-item?url=...&id=...&type=...

Fetch QTI content. For assessments, also fetches the individual questions.
Uses Cognito token (tries QTI scope, falls back to regular).
"""

from http.server import BaseHTTPRequestHandler
import requests
from api._helpers import CLIENT_ID, CLIENT_SECRET, send_json, get_query_params, get_token

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"
API_BASE = "https://api.alpha-1edtech.ai"

TYPE_MAP = {
    "stimulus": "stimuli", "stimuli": "stimuli",
    "item": "items", "items": "items",
    "assessment": "assessments", "assessments": "assessments",
    "assessment-test": "assessment-tests", "assessment-tests": "assessment-tests",
}


def _get_token():
    """Get Cognito token, try QTI scope first."""
    try:
        resp = requests.post(COGNITO_URL, headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "scope": "qti/v3/scope/admin"}, timeout=10)
        if resp.status_code == 200:
            return resp.json()["access_token"]
    except Exception:
        pass
    return get_token()


def _fetch(url, headers):
    """Fetch a URL, return (json_data, status) or (None, status)."""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json(), 200
        return None, resp.status_code
    except Exception:
        return None, 0


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        item_id = params.get("id", "").strip()
        item_type = params.get("type", "items").strip().lower()
        direct_url = params.get("url", "").strip()

        if not item_id and not direct_url:
            send_json(self, {"error": "Need id or url"}, 400)
            return

        try:
            token = _get_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

            # ── Direct URL fetch ──
            if direct_url:
                data, st = _fetch(direct_url, headers)

                if data:
                    # Detect assessment-test in multiple possible locations
                    test = data.get("qti-assessment-test")
                    if not test and isinstance(data.get("content"), dict):
                        test = data["content"].get("qti-assessment-test")
                    
                    # Also detect top-level qti-test-part (different API response format)
                    top_parts = data.get("qti-test-part")
                    if not test and top_parts:
                        test = {"qti-test-part": top_parts, "_attributes": {"title": data.get("title", "")}}

                    if test:
                        questions = self._fetch_assessment_questions(test, headers)
                        title = data.get("title") or (test.get("_attributes") or {}).get("title", "")
                        send_json(self, {"data": {"title": title, "questions": questions, "totalQuestions": len(questions)}, "success": True})
                        return

                    # Stimulus
                    if data.get("qti-assessment-stimulus"):
                        send_json(self, {"data": data, "success": True})
                        return

                    send_json(self, {"data": data, "success": True})
                    return

                send_json(self, {"error": f"URL returned {st}", "success": False}, st or 404)
                return

            # ── Fetch by ID ──
            seg = TYPE_MAP.get(item_type, "items")

            # Try to get the assessment items directly (questions endpoint)
            if item_type in ("assessment", "assessments", "assessment-test", "assessment-tests"):
                # Try: /qti/v3/assessments/{id}/items (gets actual questions)
                for base in [QTI_BASE, API_BASE]:
                    data, st = _fetch(f"{base}/api/assessments/{item_id}/items", headers)
                    if data:
                        send_json(self, {"data": data, "success": True})
                        return

                    data, st = _fetch(f"{base}/qti/v3/assessments/{item_id}/items", headers)
                    if data:
                        send_json(self, {"data": data, "success": True})
                        return

                # Try PowerPath quiz questions
                data, st = _fetch(f"{API_BASE}/powerpath/quizzes/{item_id}/questions", headers)
                if data:
                    send_json(self, {"data": data, "success": True})
                    return

            # Standard fetch by type/id
            for base in [QTI_BASE, API_BASE]:
                for path in [f"/api/{seg}/{item_id}", f"/qti/v3/{seg}/{item_id}"]:
                    data, st = _fetch(f"{base}{path}", headers)
                    if data:
                        # If assessment-test, resolve questions
                        test = data.get("qti-assessment-test") if isinstance(data, dict) else None
                        if test:
                            questions = self._fetch_assessment_questions(test, headers)
                            title = (test.get("_attributes") or {}).get("title", "")
                            send_json(self, {"data": {"title": title, "questions": questions, "totalQuestions": len(questions)}, "success": True})
                            return
                        send_json(self, {"data": data, "success": True})
                        return

            send_json(self, {"error": "Not found", "success": False}, 404)

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)

    def _fetch_assessment_questions(self, test, headers):
        """Extract question href URLs from assessment-test and fetch each one."""
        parts = test.get("qti-test-part", [])
        if not isinstance(parts, list):
            parts = [parts]

        hrefs = []
        for part in parts:
            sections = part.get("qti-assessment-section", [])
            if not isinstance(sections, list):
                sections = [sections]
            for section in sections:
                refs = section.get("qti-assessment-item-ref", [])
                if not isinstance(refs, list):
                    refs = [refs]
                for ref in refs:
                    # Handle both formats: {href: "..."} and {_attributes: {href: "..."}}
                    href = ref.get("href", "")
                    if not href:
                        href = (ref.get("_attributes") or {}).get("href", "")
                    if href:
                        hrefs.append(href)

        # Fetch individual questions (limit to 20 to avoid Vercel timeout)
        questions = []
        for href in hrefs[:20]:
            data, st = _fetch(href, headers)
            if data:
                questions.append(data)

        return questions
