"""GET /api/qti-item?url=...&id=...&type=...

Fetch QTI content (assessments, stimuli, items).

Endpoint priority (per API docs):
  1. /api/v1/qti/assessment-tests/<id>/questions/  — direct questions list
  2. /api/v1/qti/assessment-tests/<id>/            — test structure → resolve refs
  3. /api/v1/qti/stimuli/<id>/                     — shared stimulus content
  4. /powerpath/assessments/<id>                    — PowerPath metadata fallback
  5. Legacy /qti/v3/ and /api/ paths               — backward compat
"""

from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import CLIENT_ID, CLIENT_SECRET, send_json, get_query_params, get_token

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"
API_BASE = "https://api.alpha-1edtech.ai"


def _get_token():
    """Get Cognito token, try QTI admin scope first."""
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


def _fetch(url, headers):
    """Fetch a URL, return (json_data, status) or (None, status)."""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json(), 200
        return None, resp.status_code
    except Exception:
        return None, 0


def _try_fetch(urls, headers):
    """Try multiple URLs in order, return first success."""
    for url in urls:
        data, st = _fetch(url, headers)
        if data:
            return data, st
    return None, 404


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

        errors = []

        try:
            token = _get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            # ── Direct URL fetch ──────────────────────────────────
            if direct_url:
                data, st = _fetch(direct_url, headers)

                if data:
                    result = _process_response(self, data, headers)
                    if result:
                        return
                    # If not a special type, return raw
                    send_json(self, {"data": data, "success": True})
                    return

                errors.append(f"Direct URL returned {st}")

                # If direct URL failed, try to extract an ID from it and fetch by ID
                # e.g. ".../assessment-tests/frq-aphg-unit1" → id = "frq-aphg-unit1"
                parts = direct_url.rstrip("/").split("/")
                if len(parts) >= 2:
                    guessed_id = parts[-1]
                    guessed_type = parts[-2] if len(parts) >= 2 else "assessment-tests"
                    # Fall through to ID-based fetch
                    if not item_id:
                        item_id = guessed_id
                        item_type = guessed_type

                if not item_id:
                    send_json(
                        self,
                        {"error": "; ".join(errors), "success": False},
                        404,
                    )
                    return

            # ── Fetch by ID ───────────────────────────────────────
            if item_type in ("assessment", "assessments", "assessment-test", "assessment-tests"):
                result = self._fetch_assessment(item_id, headers, errors)
                if result:
                    return

            elif item_type in ("stimulus", "stimuli"):
                result = self._fetch_stimulus(item_id, headers, errors)
                if result:
                    return

            # ── Generic fetch: try multiple paths ─────────────────
            type_segments = {
                "stimulus": "stimuli", "stimuli": "stimuli",
                "item": "items", "items": "items",
                "assessment": "assessment-tests", "assessments": "assessment-tests",
                "assessment-test": "assessment-tests", "assessment-tests": "assessment-tests",
            }
            seg = type_segments.get(item_type, "items")

            urls_to_try = [
                # Documented QTI endpoints
                f"{API_BASE}/api/v1/qti/{seg}/{item_id}/",
                f"{API_BASE}/api/v1/qti/{seg}/{item_id}",
                # Legacy paths
                f"{QTI_BASE}/api/{seg}/{item_id}",
                f"{QTI_BASE}/qti/v3/{seg}/{item_id}",
                f"{API_BASE}/qti/v3/{seg}/{item_id}",
                # PowerPath fallback
                f"{API_BASE}/powerpath/items/{item_id}",
            ]

            data, st = _try_fetch(urls_to_try, headers)
            if data:
                result = _process_response(self, data, headers)
                if result:
                    return
                send_json(self, {"data": data, "success": True})
                return

            errors.append("Not found at any endpoint")
            send_json(
                self,
                {"error": "; ".join(errors), "success": False},
                404,
            )

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)

    # ── Assessment fetching ───────────────────────────────────

    def _fetch_assessment(self, test_id, headers, errors):
        """Fetch an assessment test and its questions. Returns True if handled."""

        # 1. Try /api/v1/qti/assessment-tests/{id}/questions/ (direct questions)
        questions_urls = [
            f"{API_BASE}/api/v1/qti/assessment-tests/{test_id}/questions/",
            f"{API_BASE}/api/v1/qti/assessment-tests/{test_id}/questions",
            f"{QTI_BASE}/api/assessment-tests/{test_id}/questions",
        ]
        data, st = _try_fetch(questions_urls, headers)
        if data:
            questions = data if isinstance(data, list) else data.get("questions", data.get("items", []))
            send_json(self, {
                "data": {"title": data.get("title", ""), "questions": questions, "totalQuestions": len(questions)},
                "success": True,
            })
            return True

        # 2. Try /api/v1/qti/assessment-tests/{id}/ (test structure → resolve refs)
        test_urls = [
            f"{API_BASE}/api/v1/qti/assessment-tests/{test_id}/",
            f"{API_BASE}/api/v1/qti/assessment-tests/{test_id}",
            f"{QTI_BASE}/api/assessment-tests/{test_id}",
            f"{QTI_BASE}/qti/v3/assessment-tests/{test_id}",
        ]
        data, st = _try_fetch(test_urls, headers)
        if data:
            test = data.get("qti-assessment-test", data)
            if isinstance(test, dict) and (test.get("qti-test-part") or test.get("testParts")):
                questions = self._resolve_questions(test, headers)
                title = data.get("title") or (test.get("_attributes") or {}).get("title", "")
                send_json(self, {
                    "data": {"title": title, "questions": questions, "totalQuestions": len(questions)},
                    "success": True,
                })
                return True
            # Return raw data if structure not recognized
            send_json(self, {"data": data, "success": True})
            return True

        # 3. PowerPath assessments endpoint
        pp_urls = [
            f"{API_BASE}/powerpath/assessments/{test_id}",
            f"{API_BASE}/powerpath/quizzes/{test_id}",
            f"{API_BASE}/powerpath/quizzes/{test_id}/questions",
        ]
        data, st = _try_fetch(pp_urls, headers)
        if data:
            # PowerPath may return questions directly or a quiz object
            questions = []
            if isinstance(data, list):
                questions = data
            elif isinstance(data, dict):
                questions = data.get("questions", data.get("items", []))
            if questions:
                send_json(self, {
                    "data": {"title": data.get("title", ""), "questions": questions, "totalQuestions": len(questions)},
                    "success": True,
                })
                return True
            send_json(self, {"data": data, "success": True})
            return True

        errors.append(f"Assessment {test_id} not found")
        return False

    # ── Stimulus fetching ─────────────────────────────────────

    def _fetch_stimulus(self, stim_id, headers, errors):
        """Fetch a stimulus. Returns True if handled."""
        urls = [
            f"{API_BASE}/api/v1/qti/stimuli/{stim_id}/",
            f"{API_BASE}/api/v1/qti/stimuli/{stim_id}",
            f"{QTI_BASE}/api/stimuli/{stim_id}",
            f"{QTI_BASE}/qti/v3/stimuli/{stim_id}",
        ]
        data, st = _try_fetch(urls, headers)
        if data:
            send_json(self, {"data": data, "success": True})
            return True
        errors.append(f"Stimulus {stim_id} not found")
        return False

    # ── Question resolution from test structure ───────────────

    def _resolve_questions(self, test, headers):
        """Extract question refs from assessment-test structure and fetch each one."""
        parts = test.get("qti-test-part", test.get("testParts", []))
        if not isinstance(parts, list):
            parts = [parts]

        hrefs = []
        for part in parts:
            sections = part.get("qti-assessment-section", part.get("sections", []))
            if not isinstance(sections, list):
                sections = [sections]
            for section in sections:
                refs = section.get("qti-assessment-item-ref", section.get("itemRefs", section.get("items", [])))
                if not isinstance(refs, list):
                    refs = [refs]
                for ref in refs:
                    if isinstance(ref, str):
                        hrefs.append(ref)
                        continue
                    href = ref.get("href", "")
                    if not href:
                        href = (ref.get("_attributes") or {}).get("href", "")
                    if not href:
                        # Try to get ID and construct URL
                        ref_id = ref.get("identifier", ref.get("id", ""))
                        if ref_id:
                            href = f"{API_BASE}/api/v1/qti/items/{ref_id}/"
                    if href:
                        hrefs.append(href)

        questions = []
        for href in hrefs:
            data, st = _fetch(href, headers)
            if data:
                questions.append(data)
        return questions


def _process_response(handler, data, headers):
    """Check if data is a special type (assessment-test, stimulus) and handle it.
    Returns True if handled, False otherwise."""
    if not isinstance(data, dict):
        return False

    # Assessment test
    test = data.get("qti-assessment-test")
    if not test and isinstance(data.get("content"), dict):
        test = data["content"].get("qti-assessment-test")
    top_parts = data.get("qti-test-part")
    if not test and top_parts:
        test = {"qti-test-part": top_parts, "_attributes": {"title": data.get("title", "")}}

    if test:
        questions = handler._resolve_questions(test, headers)
        title = data.get("title") or (test.get("_attributes") or {}).get("title", "")
        send_json(handler, {
            "data": {"title": title, "questions": questions, "totalQuestions": len(questions)},
            "success": True,
        })
        return True

    # Stimulus
    if data.get("qti-assessment-stimulus"):
        send_json(handler, {"data": data, "success": True})
        return True

    return False
