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
import traceback as _tb

# #region agent log — diagnostic import wrapper
_import_error = None
try:
    import requests
    from api._helpers import CLIENT_ID, CLIENT_SECRET, send_json, get_query_params, get_token
    from _kv import kv_list_get
except Exception as _e:
    _import_error = f"{type(_e).__name__}: {_e}\n{_tb.format_exc()}"
    # Provide stubs so the module still loads
    CLIENT_ID = ""; CLIENT_SECRET = ""; send_json = None; get_query_params = None; get_token = None; kv_list_get = None
    import requests
# #endregion

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


def _resolve_bank_to_qti(bank_id):
    """Transform a PowerPath bank ID to QTI test and item IDs.

    PowerPath: HUMG20-r173056-bank-v1
    QTI test:  HUMG20-qti173056-test-v1
    Pattern:   replace 'r{num}' with 'qti{num}', replace 'bank' with 'test'

    Also try: HUMG20-r173056-test-v1, HUMG20-r173056-v1
    """
    import re
    ids = []
    if "-bank-" in bank_id:
        # Primary: r→qti, bank→test
        ids.append(re.sub(r'-r(\d+)-bank-', r'-qti\1-test-', bank_id))
        # Also try: just replace bank→test (keep r prefix)
        ids.append(bank_id.replace("-bank-", "-test-"))
        # Also try: remove -bank entirely
        ids.append(bank_id.replace("-bank-", "-"))
    elif "-r" in bank_id:
        # Not a bank ID but has resource number — try qti prefix
        ids.append(re.sub(r'-r(\d+)-', r'-qti\1-', bank_id))
    return ids


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


def _get_blocked_question_ids():
    """Return set of question IDs that should be hidden (globally hidden + permanently bad)."""
    try:
        hidden = set(kv_list_get("globally_hidden_questions"))
        bad = set(kv_list_get("bad_questions"))
        return hidden | bad
    except Exception:
        return set()


def _filter_blocked_questions(questions):
    """Remove any questions whose ID is in the blocked set."""
    blocked = _get_blocked_question_ids()
    if not blocked:
        return questions
    filtered = []
    for q in questions:
        if not isinstance(q, dict):
            filtered.append(q)
            continue
        qid = q.get("identifier") or q.get("id") or ""
        if qid not in blocked:
            filtered.append(q)
    return filtered


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

    # #region agent log — diagnostic error reporter
    def _diag(self):
        import json as _j
        if _import_error:
            self.send_response(500)
            self.send_header("Content-Type","application/json")
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            self.wfile.write(_j.dumps({"_diag":"import_error","error":_import_error}).encode())
            return True
        return False
    # #endregion

    def do_GET(self):
        # #region agent log
        if self._diag(): return
        # #endregion
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

            # ── Fetch by ID ───────────────────────────────────────
            # _fetch_assessment handles bank→QTI ID transformation internally
            original_id = item_id
            if item_type in ("assessment", "assessments", "assessment-test", "assessment-tests", "assessment-bank"):
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

        # 0. Transform PowerPath bank ID to QTI test ID
        #    HUMG20-r173056-bank-v1 → HUMG20-qti173056-test-v1
        qti_ids = _resolve_bank_to_qti(test_id)
        all_ids = qti_ids + [test_id]  # Try transformed IDs first, then original

        # 1. Direct QTI fetch — try all ID variants
        for try_id in all_ids:
            for endpoint in ["assessment-tests", "assessment-items"]:
                data, st = _fetch(f"{QTI_BASE}/api/{endpoint}/{try_id}", headers)
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

        # 1b. Try OneRoster Resources API to resolve PowerPath ID → QTI URL
        #     GET /resources?filter=sourcedId~'{resource_number}'
        import re as _re
        res_match = _re.search(r'r(\d+)', test_id)
        if res_match:
            res_num = res_match.group(1)
            try:
                from api._helpers import fetch_with_params
                res_data, res_st = fetch_with_params(
                    "/ims/oneroster/resources/v1p2/resources",
                    {"filter": f"sourcedId~'{res_num}'", "limit": 10},
                )
                if res_data:
                    resources = res_data.get("resources", [])
                    for res in resources:
                        meta = res.get("metadata") or {}
                        qti_url = meta.get("url") or ""
                        if qti_url and "qti" in qti_url:
                            data, st = _fetch(qti_url, headers)
                            if data:
                                test = data.get("qti-assessment-test", data) if isinstance(data, dict) else data
                                if isinstance(test, dict) and (test.get("qti-test-part") or test.get("testParts")):
                                    questions = self._resolve_questions(test, headers)
                                    title = data.get("title") or (test.get("_attributes") or {}).get("title", "")
                                    send_json(self, {
                                        "data": {"title": title, "questions": questions, "totalQuestions": len(questions)},
                                        "success": True,
                                    })
                                    return True
                                send_json(self, {"data": data, "success": True})
                                return True
            except Exception:
                pass

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
        """Extract items + stimuli from test. Uses two-pass approach for speed:
        Pass 1: Collect all item hrefs and stimulus IDs
        Pass 2: Fetch items in parallel, then fetch unique stimuli, then attach.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        parts = test.get("qti-test-part", test.get("testParts", []))
        if not isinstance(parts, list):
            parts = [parts]

        # Pass 1: Collect refs from all sections
        item_hrefs = []
        section_stim_map = {}  # item_href → stimulus_key
        stim_keys_to_fetch = {}  # stim_key → best URL to fetch

        for part in parts:
            sections = part.get("qti-assessment-section", part.get("sections", []))
            if not isinstance(sections, list):
                sections = [sections]
            for section in sections:
                # Section-level stimulus
                sec_stim_key = ""
                stim_refs = section.get("qti-assessment-stimulus-ref", [])
                if not isinstance(stim_refs, list):
                    stim_refs = [stim_refs]
                for sref in (stim_refs or []):
                    if not sref:
                        continue
                    if isinstance(sref, str):
                        sec_stim_key = sref
                        stim_keys_to_fetch[sref] = sref
                    else:
                        attrs = sref.get("_attributes", sref)
                        shref = attrs.get("href", "")
                        sid = attrs.get("identifier", "")
                        sec_stim_key = shref or sid
                        if shref:
                            stim_keys_to_fetch[sec_stim_key] = shref
                        elif sid:
                            stim_keys_to_fetch[sec_stim_key] = f"{QTI_BASE}/api/stimuli/{sid}"

                # Item refs
                refs = section.get("qti-assessment-item-ref", section.get("itemRefs", section.get("items", [])))
                if not isinstance(refs, list):
                    refs = [refs]
                for ref in refs:
                    href = ""
                    if isinstance(ref, str):
                        href = ref
                    else:
                        href = ref.get("href", "") or (ref.get("_attributes") or {}).get("href", "")
                        if not href:
                            ref_id = ref.get("identifier", ref.get("id", ""))
                            if ref_id:
                                href = f"{QTI_BASE}/api/assessment-items/{ref_id}"
                    if href:
                        item_hrefs.append(href)
                        if sec_stim_key:
                            section_stim_map[href] = sec_stim_key

        # Pass 2: Fetch all items in parallel (max 5 threads)
        items_by_href = {}
        def fetch_item(url):
            return url, _fetch(url, headers)

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch_item, h) for h in item_hrefs]
            for f in as_completed(futures):
                try:
                    url, (data, st) = f.result()
                    if data:
                        items_by_href[url] = data
                except Exception:
                    pass

        # Check items for embedded stimulus refs (can be at multiple nesting levels)
        for href, item in items_by_href.items():
            if href in section_stim_map:
                continue
            if not isinstance(item, dict):
                continue
            # Check multiple locations for stimulus ref
            stim_ref = None
            # Level 1: item.content.qti-assessment-item.qti-assessment-stimulus-ref
            if isinstance(item.get("content"), dict):
                qi = item["content"].get("qti-assessment-item", {})
                if isinstance(qi, dict):
                    stim_ref = qi.get("qti-assessment-stimulus-ref")
            # Level 2: item.qti-assessment-stimulus-ref (top level)
            if not stim_ref:
                stim_ref = item.get("qti-assessment-stimulus-ref")
            # Level 3: check responseDeclarations metadata for stimulus ID
            if not stim_ref and isinstance(item.get("metadata"), dict):
                sid = item["metadata"].get("stimulusId") or item["metadata"].get("stimulus_id") or ""
                if sid:
                    stim_ref = {"_attributes": {"identifier": sid}}

            if stim_ref:
                attrs = stim_ref.get("_attributes", stim_ref) if isinstance(stim_ref, dict) else {}
                shref = attrs.get("href", "")
                sid = attrs.get("identifier", "")
                key = shref or sid
                if key:
                    section_stim_map[href] = key
                    if key not in stim_keys_to_fetch:
                        # Try multiple URL patterns for the stimulus
                        if shref:
                            stim_keys_to_fetch[key] = shref
                        elif sid:
                            stim_keys_to_fetch[key] = f"{QTI_BASE}/api/stimuli/{sid}"

        # Pass 3: Fetch unique stimuli in parallel (try multiple URL patterns)
        stimulus_cache = {}
        if stim_keys_to_fetch:
            def fetch_stim(key_url):
                key, primary_url = key_url
                # Try primary URL first
                data, st = _fetch(primary_url, headers)
                if data:
                    return key, data
                # Try alternate URL patterns
                sid = key.split("/")[-1] if "/" in key else key
                for alt in [
                    f"{QTI_BASE}/api/stimuli/{sid}",
                    f"{QTI_BASE}/api/assessment-stimuli/{sid}",
                    f"{QTI_BASE}/api/assessment-items/{sid}",
                ]:
                    if alt != primary_url:
                        data, st = _fetch(alt, headers)
                        if data:
                            return key, data
                return key, None

            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = [pool.submit(fetch_stim, (k, u)) for k, u in stim_keys_to_fetch.items() if u]
                for f in as_completed(futures):
                    try:
                        key, data = f.result()
                        if data:
                            stimulus_cache[key] = data
                    except Exception:
                        pass

        # Build final question list in order, with stimuli attached
        questions = []
        for href in item_hrefs:
            item = items_by_href.get(href)
            if not item:
                continue
            if isinstance(item, dict):
                stim_key = section_stim_map.get(href)
                if stim_key and stim_key in stimulus_cache:
                    item["_sectionStimulus"] = stimulus_cache[stim_key]
            questions.append(item)

        # Filter out globally hidden and permanently bad questions
        questions = _filter_blocked_questions(questions)

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
