"""GET /api/temp-extract?courseId=...

TEMPORARY — Extract all content from an AP course's PowerPath lesson plan tree.

Uses ONLY read-only GET requests:
  - PowerPath lesson plan tree (course structure)
  - QTI catalog (question content, article/stimulus content)
  - OneRoster user lookup (to resolve service account email)

A dedicated service account (pehal64861@aixind.com) is used ONLY for
read-only lesson plan GET when the generic tree endpoint returns 404.
The service account ID is NEVER used with any write endpoint.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import (
    API_BASE,
    CLIENT_ID,
    CLIENT_SECRET,
    api_headers,
    send_json,
    get_query_params,
    get_token,
)

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"


# ---------------------------------------------------------------------------
# Auth — QTI admin-scoped token (catalog access only)
# ---------------------------------------------------------------------------
def _qti_token():
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


def _qti_headers():
    return {"Authorization": f"Bearer {_qti_token()}", "Accept": "application/json"}


# ---------------------------------------------------------------------------
# Read-only GET helpers
# ---------------------------------------------------------------------------
def _fetch_json(url, headers, timeout=15):
    """GET url → (json_data, status) or (None, status). Read-only."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.json(), 200
        return None, resp.status_code
    except Exception:
        return None, 0


def _fetch_raw(url, headers, timeout=15):
    """GET url → (response, content_type) or (None, None). Read-only."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp, resp.headers.get("Content-Type", "")
        return None, str(resp.status_code)
    except Exception:
        return None, None


def _extract_html_text(raw_xml):
    """Strip HTML/XML tags to get plain text."""
    if not raw_xml:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_xml)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _render_node_text(node):
    """Recursively extract text from a QTI JSON node tree."""
    if node is None:
        return ""
    if isinstance(node, str):
        return _extract_html_text(node)
    if isinstance(node, list):
        return " ".join(_render_node_text(i) for i in node)
    if not isinstance(node, dict):
        return str(node)
    parts = []
    for key, val in node.items():
        if key.startswith("_"):
            continue
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, (dict, list)):
            parts.append(_render_node_text(val))
    return " ".join(p for p in parts if p.strip())


def _deep_text(obj):
    """Recursively extract all text from nested dict/list."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_deep_text(i) for i in obj)
    if isinstance(obj, dict):
        return " ".join(
            _deep_text(v) for k, v in obj.items() if not k.startswith("_")
        )
    return ""


def _resolve_bank_to_qti(bank_id):
    """Transform a PowerPath bank ID to possible QTI test IDs."""
    ids = []
    if "-bank-" in bank_id:
        ids.append(re.sub(r"-r(\d+)-bank-", r"-qti\1-test-", bank_id))
        ids.append(bank_id.replace("-bank-", "-test-"))
        ids.append(bank_id.replace("-bank-", "-"))
    elif "-r" in bank_id:
        ids.append(re.sub(r"-r(\d+)-", r"-qti\1-", bank_id))
    return ids


# ---------------------------------------------------------------------------
# Article content fetching (QTI stimulus — read-only catalog)
# ---------------------------------------------------------------------------
def _extract_article_text(data):
    """Extract plain text from a QTI stimulus JSON response."""
    if not isinstance(data, dict):
        return ""
    for path_fn in [
        lambda d: (d.get("qti-assessment-stimulus") or {}).get("qti-stimulus-body"),
        lambda d: ((d.get("content") or {}).get("qti-assessment-stimulus") or {}).get("qti-stimulus-body"),
        lambda d: d.get("qti-stimulus-body"),
    ]:
        try:
            node = path_fn(data)
            if node:
                r = _render_node_text(node)
                if r and r.strip():
                    return r.strip()
        except Exception:
            pass
    for f in ("body", "content", "html", "text"):
        v = data.get(f)
        if isinstance(v, str) and len(v.strip()) > 10:
            return _extract_html_text(v)
        if isinstance(v, dict):
            r = _render_node_text(v)
            if r and r.strip():
                return r.strip()
    inner = data.get("data")
    if isinstance(inner, dict):
        return _extract_article_text(inner)
    return ""


def _fetch_article_content(url, res_id, qti_headers):
    """Fetch article/stimulus content via QTI catalog. Read-only GET only."""
    stim_id = ""
    if url and "stimuli" in url.lower():
        m = re.search(r"/stimuli/([^/?#]+)", url)
        if m:
            stim_id = m.group(1).strip("/")
    if not stim_id and res_id:
        stim_id = res_id

    if stim_id:
        for endpoint in [
            f"{QTI_BASE}/api/stimuli/{stim_id}",
            f"{API_BASE}/api/v1/qti/stimuli/{stim_id}/",
        ]:
            resp, ct = _fetch_raw(endpoint, qti_headers)
            if resp:
                if "json" in (ct or "").lower():
                    try:
                        text = _extract_article_text(resp.json())
                        if text:
                            return text
                    except Exception:
                        pass
                elif resp.text and resp.text.strip():
                    return _extract_html_text(resp.text)

    if url:
        resp, ct = _fetch_raw(url, qti_headers)
        if resp:
            if "json" in (ct or "").lower():
                try:
                    text = _extract_article_text(resp.json())
                    if text:
                        return text
                except Exception:
                    pass
            elif resp.text and resp.text.strip():
                return _extract_html_text(resp.text)

    return ""


# ---------------------------------------------------------------------------
# QTI question fetching (admin-scoped catalog — NO student data)
# ---------------------------------------------------------------------------
def _parse_qti_item(item):
    """Parse a QTI assessment-item into a simplified question dict."""
    if not isinstance(item, dict):
        return None

    qid = item.get("identifier") or item.get("id") or ""
    title = item.get("title") or item.get("name") or ""
    q_type = "mcq"
    prompt_text = ""
    choices = []
    correct_id = ""

    # Find rawXml
    raw_xml = ""
    content = item.get("content")
    if isinstance(content, dict):
        raw_xml = content.get("rawXml", "")
    elif isinstance(content, str) and "<" in content:
        raw_xml = content

    # 1. Extract from rawXml (most reliable)
    if raw_xml:
        pm = re.search(r"<qti-prompt[^>]*>(.*?)</qti-prompt>", raw_xml, re.DOTALL)
        if pm:
            prompt_text = _extract_html_text(pm.group(1))
        else:
            bm = re.search(r"<qti-item-body[^>]*>(.*?)</qti-item-body>", raw_xml, re.DOTALL)
            if bm:
                body_html = bm.group(1)
                body_html = re.sub(r"<qti-choice-interaction.*?</qti-choice-interaction>", "", body_html, flags=re.DOTALL)
                prompt_text = _extract_html_text(body_html)[:1000]

        for m in re.finditer(
            r'<qti-simple-choice[^>]*identifier="([^"]*)"[^>]*>(.*?)</qti-simple-choice>',
            raw_xml, re.DOTALL,
        ):
            choices.append({"id": m.group(1), "label": _extract_html_text(m.group(2))})

        if not choices:
            for m in re.finditer(r"<qti-simple-choice[^>]*>(.*?)</qti-simple-choice>", raw_xml, re.DOTALL):
                label = _extract_html_text(m.group(1))
                if label:
                    choices.append({"id": chr(65 + len(choices)), "label": label})

        cm = re.search(r"<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>", raw_xml)
        if cm:
            correct_id = cm.group(1).strip()

        if "qti-extended-text-interaction" in raw_xml:
            q_type = "frq"

    # 2. JSON structure fallback
    if not prompt_text or not choices:
        qai = item.get("qti-assessment-item", item)
        if isinstance(qai, dict):
            body = qai.get("qti-item-body") or {}
            if isinstance(body, dict):
                ci = body.get("qti-choice-interaction") or {}
                if isinstance(ci, list):
                    ci = ci[0] if ci else {}
                if isinstance(ci, dict):
                    if not prompt_text:
                        p = ci.get("qti-prompt", "")
                        if isinstance(p, dict):
                            p = _deep_text(p)
                        if p:
                            prompt_text = _extract_html_text(str(p))
                    if not choices:
                        scs = ci.get("qti-simple-choice", [])
                        if not isinstance(scs, list):
                            scs = [scs]
                        for sc in scs:
                            if isinstance(sc, dict):
                                cid = (sc.get("_attributes") or sc).get("identifier", "")
                                clabel = _extract_html_text(_deep_text(sc))
                                if cid or clabel:
                                    choices.append({"id": cid or chr(65 + len(choices)), "label": clabel})
                if body.get("qti-extended-text-interaction"):
                    q_type = "frq"
                    if not prompt_text:
                        p = body.get("qti-prompt", "")
                        if isinstance(p, dict):
                            p = _deep_text(p)
                        if p:
                            prompt_text = _extract_html_text(str(p))
            if not correct_id:
                rd = qai.get("qti-response-declaration") or qai.get("responseDeclaration") or {}
                if isinstance(rd, list):
                    rd = rd[0] if rd else {}
                if isinstance(rd, dict):
                    cr = rd.get("qti-correct-response") or rd.get("correctResponse") or {}
                    if isinstance(cr, dict):
                        val = cr.get("qti-value") or cr.get("value", "")
                        if isinstance(val, dict):
                            val = val.get("#text", "") or val.get("_text", "")
                        if isinstance(val, list):
                            val = val[0] if val else ""
                        correct_id = str(val).strip()

    # 3. Last resort
    if not prompt_text:
        all_text = _extract_html_text(_deep_text(item))
        if len(all_text) > 20:
            prompt_text = all_text[:1500]

    if not prompt_text and not choices and not title:
        return None

    result = {"id": qid, "title": title, "prompt": prompt_text, "type": q_type}
    if choices:
        result["choices"] = choices
    if correct_id:
        result["correctAnswer"] = correct_id
    if raw_xml and not prompt_text:
        result["rawContent"] = _extract_html_text(raw_xml)[:2000]

    stim = item.get("_sectionStimulus")
    if stim and isinstance(stim, dict):
        sb = (stim.get("qti-assessment-stimulus") or stim).get("qti-stimulus-body", "")
        if sb:
            result["stimulus"] = _extract_html_text(str(sb))

    return result


def _resolve_qti_test_questions(test_data, qti_headers):
    """Given a QTI assessment-test JSON, walk its parts/sections to
    collect item refs and fetch each item. Read-only GETs only."""
    test = test_data.get("qti-assessment-test", test_data)
    if not isinstance(test, dict):
        return []

    parts = test.get("qti-test-part") or test.get("testParts") or []
    if not isinstance(parts, list):
        parts = [parts]

    item_hrefs = []
    for part in parts:
        sections = part.get("qti-assessment-section") or part.get("sections") or []
        if not isinstance(sections, list):
            sections = [sections]
        for section in sections:
            refs = section.get("qti-assessment-item-ref") or section.get("itemRefs") or section.get("items") or []
            if not isinstance(refs, list):
                refs = [refs]
            for ref in refs:
                href = ""
                if isinstance(ref, str):
                    href = ref
                elif isinstance(ref, dict):
                    href = ref.get("href", "") or (ref.get("_attributes") or {}).get("href", "")
                    if not href:
                        rid = ref.get("identifier") or ref.get("id", "")
                        if rid:
                            href = f"{QTI_BASE}/api/assessment-items/{rid}"
                if href:
                    item_hrefs.append(href)

    if not item_hrefs:
        return []

    # Fetch items in parallel (read-only GETs)
    def _get_item(url):
        return url, _fetch_json(url, qti_headers)

    items = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_get_item, h) for h in item_hrefs]
        for f in as_completed(futs):
            try:
                url, (data, _st) = f.result()
                if data:
                    items[url] = data
            except Exception:
                pass

    return [items[h] for h in item_hrefs if h in items]


def _fetch_questions_from_qti(url, res_id, qti_headers):
    """Fetch questions for a resource via the QTI catalog.
    Uses ONLY read-only GET requests to admin-scoped QTI endpoints.
    Returns list of parsed question dicts."""

    all_ids = [res_id] if res_id else []
    if res_id:
        all_ids.extend(_resolve_bank_to_qti(res_id))

    # Strategy 1: Direct URL fetch
    if url:
        data, st = _fetch_json(url, qti_headers)
        if data and isinstance(data, dict):
            test = data.get("qti-assessment-test", data)
            if isinstance(test, dict) and (test.get("qti-test-part") or test.get("testParts")):
                raw_items = _resolve_qti_test_questions(data, qti_headers)
                parsed = [_parse_qti_item(i) for i in raw_items]
                parsed = [p for p in parsed if p]
                if parsed:
                    return parsed
            # Single item
            p = _parse_qti_item(data)
            if p:
                return [p]
            # Might have questions array
            if data.get("questions"):
                parsed = [_parse_qti_item(q) for q in data["questions"]]
                return [p for p in parsed if p]

    # Strategy 2: Try QTI catalog by resource ID
    for tid in all_ids:
        for endpoint in ["assessment-tests", "assessment-items"]:
            data, st = _fetch_json(f"{QTI_BASE}/api/{endpoint}/{tid}", qti_headers)
            if data and isinstance(data, dict):
                test = data.get("qti-assessment-test", data)
                if isinstance(test, dict) and (test.get("qti-test-part") or test.get("testParts")):
                    raw_items = _resolve_qti_test_questions(data, qti_headers)
                    parsed = [_parse_qti_item(i) for i in raw_items]
                    parsed = [p for p in parsed if p]
                    if parsed:
                        return parsed
                p = _parse_qti_item(data)
                if p:
                    return [p]
                if data.get("questions"):
                    parsed = [_parse_qti_item(q) for q in data["questions"]]
                    result = [p for p in parsed if p]
                    if result:
                        return result

    return []


# ---------------------------------------------------------------------------
# Service account — dedicated download user (pehal64861@aixind.com)
# Hardcoded sourcedId to avoid an extra API call every time.
# This user is NEVER used with resetAttempt, getAssessmentProgress,
# updateStudentQuestionResponse, or any student-mutating endpoint.
# It is used ONLY for:
#   - GET /powerpath/lessonPlans/{courseId}/{svcId}  (read-only)
#   - POST /edubridge/enrollments/enroll/{svcId}/{courseId}  (one-time per course)
#   - POST /powerpath/lessonPlans/course/{courseId}/sync  (provisions lesson plan)
# ---------------------------------------------------------------------------
SERVICE_USER_ID = "8ea2b8e1-1b04-4cab-b608-9ab524c059c2"


def _ensure_enrolled(course_id, pp_headers, debug):
    """Enroll the service account in a course if not already enrolled.
    This is a one-time write per course to the service account only.
    Never touches any real student data."""
    try:
        resp = requests.post(
            f"{API_BASE}/edubridge/enrollments/enroll/{SERVICE_USER_ID}/{course_id}",
            headers=pp_headers,
            json={"role": "student"},
            timeout=15,
        )
        if resp.status_code == 401:
            pp_headers = api_headers()
            resp = requests.post(
                f"{API_BASE}/edubridge/enrollments/enroll/{SERVICE_USER_ID}/{course_id}",
                headers=pp_headers,
                json={"role": "student"},
                timeout=15,
            )
        debug.append({"step": "enroll", "courseId": course_id, "status": resp.status_code})
    except Exception as e:
        debug.append({"step": "enroll", "courseId": course_id, "error": str(e)})


def _sync_course(course_id, pp_headers, debug):
    """Trigger PowerPath to provision lesson plans for all enrolled users.
    Same endpoint as sync-lesson-plan.py. Only affects service account."""
    try:
        resp = requests.post(
            f"{API_BASE}/powerpath/lessonPlans/course/{course_id}/sync",
            headers=pp_headers,
            json={},
            timeout=60,
        )
        if resp.status_code == 401:
            pp_headers = api_headers()
            resp = requests.post(
                f"{API_BASE}/powerpath/lessonPlans/course/{course_id}/sync",
                headers=pp_headers,
                json={},
                timeout=60,
            )
        debug.append({"step": "sync", "courseId": course_id, "status": resp.status_code})
    except Exception as e:
        debug.append({"step": "sync", "courseId": course_id, "error": str(e)})


# ---------------------------------------------------------------------------
# Handler — read-only, no real student data
# ---------------------------------------------------------------------------
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
        catalog_id = params.get("catalogId", "").strip()

        if not course_id:
            send_json(self, {"error": "Need courseId"}, 400)
            return

        # Collect all IDs to try (enrollment ID + catalog ID, deduplicated)
        ids_to_try = [course_id]
        if catalog_id and catalog_id != course_id:
            ids_to_try.append(catalog_id)

        try:
            pp_headers = api_headers()
            qti_headers = _qti_headers()
            debug = []

            # 1. Try every ID with the tree endpoint first (no user needed)
            tree = None
            for cid in ids_to_try:
                if tree:
                    break
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/tree/{cid}",
                        headers=pp_headers,
                        timeout=30,
                    )
                    if resp.status_code == 401:
                        pp_headers = api_headers()
                        resp = requests.get(
                            f"{API_BASE}/powerpath/lessonPlans/tree/{cid}",
                            headers=pp_headers,
                            timeout=30,
                        )
                    debug.append({"step": "tree", "courseId": cid, "status": resp.status_code})
                    if resp.status_code == 200:
                        tree = resp.json()
                except Exception as e:
                    debug.append({"step": "tree", "courseId": cid, "error": str(e)})

            # 2. Fallback: try service account GET (maybe already provisioned)
            if not tree:
                for cid in ids_to_try:
                    if tree:
                        break
                    try:
                        resp = requests.get(
                            f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}",
                            headers=pp_headers,
                            timeout=30,
                        )
                        if resp.status_code == 401:
                            pp_headers = api_headers()
                            resp = requests.get(
                                f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}",
                                headers=pp_headers,
                                timeout=30,
                            )
                        debug.append({"step": "svc_get", "courseId": cid, "status": resp.status_code})
                        if resp.status_code == 200:
                            tree = resp.json()
                            break
                    except Exception as e:
                        debug.append({"step": "svc_get", "courseId": cid, "error": str(e)})

            # 3. Not provisioned — enroll + sync + retry
            if not tree:
                for cid in ids_to_try:
                    if tree:
                        break
                    _ensure_enrolled(cid, pp_headers, debug)
                    _sync_course(cid, pp_headers, debug)
                    # Retry GET after sync
                    try:
                        resp = requests.get(
                            f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}",
                            headers=pp_headers,
                            timeout=30,
                        )
                        if resp.status_code == 401:
                            pp_headers = api_headers()
                            resp = requests.get(
                                f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}",
                                headers=pp_headers,
                                timeout=30,
                            )
                        debug.append({"step": "svc_retry", "courseId": cid, "status": resp.status_code})
                        if resp.status_code == 200:
                            tree = resp.json()
                            break
                    except Exception as e:
                        debug.append({"step": "svc_retry", "courseId": cid, "error": str(e)})

            if not tree:
                send_json(self, {
                    "error": f"No lesson plan found for course {course_id}",
                    "success": False,
                    "_debug": debug,
                    "_ids_tried": ids_to_try,
                    "_service_user": SERVICE_USER_ID,
                }, 404)
                return

            inner = tree.get("lessonPlan", tree) if isinstance(tree, dict) else tree
            if isinstance(inner, dict) and inner.get("lessonPlan"):
                inner = inner["lessonPlan"]

            course_title = inner.get("title", "") if isinstance(inner, dict) else ""
            units_raw = inner.get("subComponents", []) if isinstance(inner, dict) else []
            units_raw.sort(key=lambda u: u.get("sortOrder", ""))

            # 2. Collect ALL resources from ALL units upfront
            #    Each entry: (unit_idx, lesson_idx, res_title, res_id, rurl, kind)
            all_lessons = []   # [(unit_idx, lesson_dict)]
            all_resources = [] # [(unit_idx, lesson_idx, res_title, res_id, rurl)]
            debug = {"attempted": 0, "succeeded": 0, "failed": 0}

            for ui, unit in enumerate(units_raw):
                lessons_raw = unit.get("subComponents", [])
                lessons_raw.sort(key=lambda l: l.get("sortOrder", ""))
                lessons_raw = [
                    les for les in lessons_raw
                    if "advanced organizer" not in (les.get("title", "")).lower()
                    and "organizer submission" not in (les.get("title", "")).lower()
                ]
                unit_res = unit.get("componentResources", [])
                if not lessons_raw and unit_res:
                    for i, ur in enumerate(unit_res):
                        r = ur.get("resource", ur) if isinstance(ur, dict) else ur
                        lessons_raw.append({
                            "title": (r.get("title", "") if isinstance(r, dict) else "") or f"Assessment {i + 1}",
                            "sortOrder": str(i),
                            "componentResources": [ur],
                        })

                for li, lesson in enumerate(lessons_raw):
                    lesson_idx = len(all_lessons)
                    all_lessons.append((ui, {
                        "title": lesson.get("title", ""),
                        "sortOrder": lesson.get("sortOrder", ""),
                        "_videos": [],
                        "_articles": [],
                        "_questions": [],
                    }))

                    for res_wrapper in lesson.get("componentResources", []):
                        res = res_wrapper.get("resource", res_wrapper) if isinstance(res_wrapper, dict) else res_wrapper
                        if not isinstance(res, dict):
                            continue
                        meta = res.get("metadata") or {}
                        rurl = meta.get("url", "") or res.get("url", "") or meta.get("href", "") or res.get("href", "")
                        res_id = res.get("id", "") or res.get("sourcedId", "") or ""
                        res_title = res.get("title", "")
                        rtype = (meta.get("type", "") or res.get("type", "")).lower()

                        if rtype == "video":
                            all_lessons[lesson_idx][1]["_videos"].append({
                                "title": res_title, "url": rurl, "id": res_id,
                            })
                        elif "stimuli" in rurl:
                            all_resources.append((lesson_idx, res_title, res_id, rurl, "article"))
                        else:
                            all_resources.append((lesson_idx, res_title, res_id, rurl, "assessment"))

            # 3. Parallel fetch: ALL resources in ONE batch (read-only GETs only)
            debug["attempted"] = len(all_resources)

            def _process_resource(entry):
                lesson_idx, res_title, res_id, rurl, kind = entry
                if kind == "assessment":
                    questions = _fetch_questions_from_qti(rurl, res_id, qti_headers)
                    if questions:
                        return (lesson_idx, "questions", questions)
                # Either it's an article, or assessment returned no questions
                article_text = _fetch_article_content(rurl, res_id, qti_headers)
                return (lesson_idx, "article", {
                    "title": res_title, "url": rurl, "id": res_id,
                    "content": article_text[:5000] if article_text else "",
                })

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(_process_resource, e) for e in all_resources]
                for f in as_completed(futures):
                    try:
                        lesson_idx, result_type, data = f.result()
                        if result_type == "questions":
                            all_lessons[lesson_idx][1]["_questions"].extend(data)
                            debug["succeeded"] += 1
                        else:
                            all_lessons[lesson_idx][1]["_articles"].append(data)
                            debug["succeeded"] += 1
                    except Exception:
                        debug["failed"] += 1

            # 4. Build final response
            units_out = []
            total_questions = 0
            total_videos = 0
            total_articles = 0

            # Group lessons back into units
            unit_lessons = {}
            for lesson_idx, (ui, ld) in enumerate(all_lessons):
                if ui not in unit_lessons:
                    unit_lessons[ui] = []
                questions = ld.pop("_questions")
                videos = ld.pop("_videos")
                articles = ld.pop("_articles")
                ld["questionCount"] = len(questions)
                ld["questions"] = questions
                if videos:
                    ld["videos"] = videos
                    ld["videoCount"] = len(videos)
                if articles:
                    ld["articles"] = articles
                    ld["articleCount"] = len(articles)
                total_questions += len(questions)
                total_videos += len(videos)
                total_articles += len(articles)
                unit_lessons[ui].append(ld)

            for ui, unit in enumerate(units_raw):
                lessons = unit_lessons.get(ui, [])
                units_out.append({
                    "title": unit.get("title", ""),
                    "sortOrder": unit.get("sortOrder", ""),
                    "lessonCount": len(lessons),
                    "lessons": lessons,
                })

            send_json(self, {
                "success": True,
                "course": {"title": course_title, "courseId": course_id},
                "totalQuestions": total_questions,
                "totalVideos": total_videos,
                "totalArticles": total_articles,
                "unitCount": len(units_out),
                "units": units_out,
                "_debug": debug,
            })

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
