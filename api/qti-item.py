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


def _match_items(items, target_subject, code, title_lower):
    """Score and rank QTI items by relevance to the search criteria."""
    scored = []
    for item in items:
        t = (item.get("title") or item.get("name") or "").lower()
        iid = (item.get("identifier") or item.get("id") or "").lower()
        score = 0
        if target_subject and target_subject in t:
            score += 3
        if code and code in iid:
            score += 3
        if code and code in t:
            score += 2
        # Match unit number from title (e.g. "unit 1" in both)
        import re
        title_units = re.findall(r'unit\s*(\d+)', title_lower)
        item_units = re.findall(r'unit\s*(\d+)', t)
        if title_units and item_units and title_units[0] == item_units[0]:
            score += 4
        if score >= 3:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored]


def _fetch_full_items(items, headers):
    """Fetch full QTI content for a list of item stubs."""
    questions = []
    for item in items:
        iid = item.get("identifier") or item.get("id") or ""
        if not iid:
            continue
        full, st = _fetch(f"{QTI_BASE}/api/assessment-items/{iid}", headers)
        if full:
            questions.append(full)
    return questions


def _resolve_powerpath_to_qti(pp_id, headers, errors):
    """Resolve a PowerPath resource ID to its QTI test/item ID.

    PowerPath items have metadata containing qti_test_id or qti_item_id.
    Fetches from /api/v1/old-powerpath/fetch-item-details/?item_id=...
    and also tries /powerpath/items/{id} to get the mapping.

    Returns the QTI ID if found, otherwise the original ID unchanged.
    """
    resolve_urls = [
        f"{API_BASE}/api/v1/old-powerpath/fetch-item-details/?item_id={pp_id}",
        f"{API_BASE}/powerpath/items/{pp_id}",
        f"{API_BASE}/powerpath/resources/{pp_id}",
        f"{API_BASE}/powerpath/content/{pp_id}",
    ]

    for url in resolve_urls:
        try:
            data, st = _fetch(url, headers)
            if not data or not isinstance(data, dict):
                continue

            # Look for QTI ID in multiple possible locations
            meta = data.get("metadata") or {}
            qti_id = (
                meta.get("qti_test_id")
                or meta.get("qti_item_id")
                or meta.get("qtiTestId")
                or meta.get("qtiItemId")
                or meta.get("qti_id")
                or meta.get("qtiId")
                or data.get("qti_test_id")
                or data.get("qti_item_id")
                or data.get("qtiTestId")
                or data.get("qtiItemId")
                or data.get("qti_id")
                or data.get("qtiId")
                or ""
            )
            if qti_id:
                return str(qti_id)

            # Also check for a nested content URL that IS the QTI resource
            content_url = (
                meta.get("content_url")
                or meta.get("url")
                or data.get("content_url")
                or data.get("url")
                or data.get("lti_url")
                or ""
            )
            if content_url and ("qti" in content_url or "assessment" in content_url):
                # Extract QTI ID from URL: .../assessment-tests/some-qti-id
                parts = content_url.rstrip("/").split("/")
                if parts:
                    return parts[-1]

        except Exception:
            continue

    errors.append(f"Could not resolve PowerPath ID '{pp_id}' to QTI ID")
    return pp_id


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
        search_subject = params.get("subject", "").strip()
        search_title = params.get("title", "").strip()
        search_grade = params.get("grade", "").strip()

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

            # ── Resolve PowerPath ID → QTI ID ─────────────────────
            # PowerPath resource IDs (like "HUMG20-r173056-bank-v1") are NOT QTI IDs.
            # We need to fetch item details from PowerPath to get the real qti_test_id.
            original_id = item_id
            qti_id = _resolve_powerpath_to_qti(item_id, headers, errors)
            if qti_id and qti_id != item_id:
                item_id = qti_id

            # ── Fetch by ID ───────────────────────────────────────
            if item_type in ("assessment", "assessments", "assessment-test", "assessment-tests"):
                result = self._fetch_assessment(item_id, headers, errors, search_subject, search_title, search_grade)
                if result:
                    return
                # If resolved ID failed, try original ID too
                if item_id != original_id:
                    result = self._fetch_assessment(original_id, headers, errors, search_subject, search_title, search_grade)
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

            # Try both resolved QTI ID and original PowerPath ID
            ids_to_try = [item_id]
            if original_id != item_id:
                ids_to_try.append(original_id)

            for try_id in ids_to_try:
                urls_to_try = [
                    # Documented QTI endpoints
                    f"{API_BASE}/api/v1/qti/{seg}/{try_id}/",
                    f"{API_BASE}/api/v1/qti/{seg}/{try_id}",
                    # Legacy paths
                    f"{QTI_BASE}/api/{seg}/{try_id}",
                    f"{QTI_BASE}/qti/v3/{seg}/{try_id}",
                    f"{API_BASE}/qti/v3/{seg}/{try_id}",
                ]

                data, st = _try_fetch(urls_to_try, headers)
                if data:
                    result = _process_response(self, data, headers)
                    if result:
                        return
                    send_json(self, {"data": data, "success": True})
                    return

            errors.append(f"Not found (tried IDs: {', '.join(ids_to_try)})")
            send_json(
                self,
                {"error": "; ".join(errors), "success": False},
                404,
            )

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)

    # ── Assessment fetching ───────────────────────────────────

    def _fetch_assessment(self, test_id, headers, errors, search_subject="", search_title="", search_grade=""):
        """Fetch an assessment test and its questions. Returns True if handled."""

        # 1. Direct QTI fetch (documented endpoints)
        #    GET https://qti.alpha-1edtech.ai/api/assessment-tests/{id}
        #    GET https://qti.alpha-1edtech.ai/api/assessment-items/{id}
        for endpoint in ["assessment-tests", "assessment-items"]:
            data, st = _fetch(f"{QTI_BASE}/api/{endpoint}/{test_id}", headers)
            if data:
                # Check if it's a test with parts → resolve questions
                test = data.get("qti-assessment-test", data) if isinstance(data, dict) else data
                if isinstance(test, dict) and (test.get("qti-test-part") or test.get("testParts")):
                    questions = self._resolve_questions(test, headers)
                    title = data.get("title") or (test.get("_attributes") or {}).get("title", "")
                    send_json(self, {
                        "data": {"title": title, "questions": questions, "totalQuestions": len(questions)},
                        "success": True,
                    })
                    return True
                # Single item or raw data
                send_json(self, {"data": data, "success": True})
                return True

        # 2. Search QTI catalog by subject/title/keywords
        catalog_result = self._search_qti_catalog(
            test_id, headers, errors,
            subject=search_subject, title=search_title, grade=search_grade,
        )
        if catalog_result:
            return True

        # 3. PowerPath item details (may contain embedded content)
        for url in [
            f"{API_BASE}/api/v1/old-powerpath/fetch-item-details/?item_id={test_id}",
            f"{API_BASE}/powerpath/items/{test_id}",
        ]:
            data, st = _fetch(url, headers)
            if data and isinstance(data, dict):
                questions = data.get("questions", data.get("items", []))
                if questions:
                    send_json(self, {
                        "data": {"title": data.get("title", ""), "questions": questions, "totalQuestions": len(questions)},
                        "success": True,
                    })
                    return True
                body = data.get("body") or data.get("content") or data.get("html") or ""
                if body:
                    send_json(self, {"data": data, "success": True})
                    return True
                # Check for nested QTI ID
                meta = data.get("metadata") or {}
                nested_qti = meta.get("qti_test_id") or meta.get("qti_id") or data.get("qti_id") or ""
                if nested_qti and nested_qti != test_id:
                    result = self._fetch_assessment(str(nested_qti), headers, errors)
                    if result:
                        return True

        # 4. PowerPath assessments/quizzes endpoint
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

    # ── Resources API search ─────────────────────────────────

    def _search_qti_catalog(self, pp_id, headers, errors, subject="", title="", grade=""):
        """Search the QTI catalog for content matching a PowerPath assessment.

        QTI API format (qti.alpha-1edtech.ai/api):
          GET /assessment-tests?limit=20&page=1  → {items:[], total, page, pages}
          GET /assessment-items?limit=20&type=extended-text  → FRQs only
          GET /assessment-items/{id}  → full item with QTI content

        Matches by course code from PowerPath ID and subject/title keywords.
        """
        code = pp_id.split("-")[0].lower() if "-" in pp_id else ""
        title_lower = (title or "").lower()

        # Map course codes to specific search terms
        code_subjects = {
            "humg": "geography", "hist": "history", "govt": "government",
            "math": "math", "engl": "english", "sci": "science",
            "read": "reading", "writ": "writing", "lang": "language",
        }
        target_subject = ""
        for prefix, subj in code_subjects.items():
            if code.startswith(prefix):
                target_subject = subj
                break
        if not target_subject and subject:
            target_subject = subject.lower().split()[0]  # First word of subject

        # Determine if this is an FRQ (extended-text) or MCQ assessment
        is_frq = "frq" in title_lower or "free response" in title_lower or "essay" in title_lower

        try:
            # 1. Try FRQ items first (type=extended-text filter)
            if is_frq or "bank" in pp_id.lower():
                data, st = _fetch(
                    f"{QTI_BASE}/api/assessment-items?type=extended-text&limit=50",
                    headers,
                )
                if data and isinstance(data, dict):
                    items = data.get("items", [])
                    matched = _match_items(items, target_subject, code, title_lower)
                    if matched:
                        questions = _fetch_full_items(matched[:10], headers)
                        if questions:
                            send_json(self, {
                                "data": {"title": title, "questions": questions, "totalQuestions": len(questions), "type": "frq"},
                                "success": True,
                            })
                            return True

            # 2. Search assessment-tests catalog
            data, st = _fetch(f"{QTI_BASE}/api/assessment-tests?limit=100", headers)
            if data and isinstance(data, dict):
                tests = data.get("items", [])
                matched_test = _match_items(tests, target_subject, code, title_lower)
                if matched_test:
                    # Fetch the full test and resolve its questions
                    tid = matched_test[0].get("identifier") or matched_test[0].get("id") or ""
                    if tid:
                        full, fst = _fetch(f"{QTI_BASE}/api/assessment-tests/{tid}", headers)
                        if full:
                            inner = full.get("qti-assessment-test", full) if isinstance(full, dict) else full
                            if isinstance(inner, dict) and (inner.get("qti-test-part") or inner.get("testParts")):
                                questions = self._resolve_questions(inner, headers)
                                t = full.get("title") or (inner.get("_attributes") or {}).get("title", "")
                                send_json(self, {
                                    "data": {"title": t or title, "questions": questions, "totalQuestions": len(questions)},
                                    "success": True,
                                })
                                return True
                            send_json(self, {"data": full, "success": True})
                            return True

            # 3. Broad search of assessment-items (all types)
            data, st = _fetch(f"{QTI_BASE}/api/assessment-items?limit=100", headers)
            if data and isinstance(data, dict):
                items = data.get("items", [])
                matched = _match_items(items, target_subject, code, title_lower)
                if matched:
                    questions = _fetch_full_items(matched[:10], headers)
                    if questions:
                        send_json(self, {
                            "data": {"title": title, "questions": questions, "totalQuestions": len(questions)},
                            "success": True,
                        })
                        return True

            errors.append(f"No QTI content found for {target_subject or code or 'search'}")
            return False

        except Exception as e:
            errors.append(f"QTI catalog search: {e}")
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
