"""GET /api/_temp_extract?courseId=...

TEMPORARY — Extract all content from an AP course's PowerPath lesson plan tree.

Walks the lesson plan tree (units → lessons → resources) and fetches:
  - Questions from assessment resources (via QTI catalog)
  - Video links
  - Article content (via QTI stimulus API)

Returns an organized JSON structure with videos, articles, and questions per lesson.

No student context needed — uses the tree endpoint and QTI catalog directly.
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
# Auth — QTI admin-scoped token (same pattern as qti-item.py)
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
# Helpers
# ---------------------------------------------------------------------------
def _fetch(url, headers, timeout=30):
    """GET url → (json, status) or (None, status)."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.json(), 200
        return None, resp.status_code
    except Exception:
        return None, 0


def _fetch_raw(url, headers, timeout=15):
    """GET url → (response, content_type) or (None, None).  Returns the raw response."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp, resp.headers.get("Content-Type", "")
        return None, str(resp.status_code)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Resource type classification (mirrors course.html resLabel logic)
# ---------------------------------------------------------------------------
def _classify_resource(res):
    """Return 'video', 'article', or 'assessment' for a componentResource."""
    meta = res.get("metadata") or {}
    rtype = (meta.get("type", "") or res.get("type", "")).lower()
    rurl = meta.get("url", "") or res.get("url", "") or meta.get("href", "") or res.get("href", "")

    if rtype == "video":
        return "video"
    if rtype in ("assessment", "quiz", "test", "exam", "frq") or "assess" in rtype or "quiz" in rtype or "test" in rtype:
        return "assessment"
    # URL-based heuristics
    if rurl:
        if "stimuli" in rurl:
            return "article"
        if "/assessment" in rurl or "/quiz" in rurl:
            return "assessment"
    return "article"


# ---------------------------------------------------------------------------
# Article content fetching (mirrors article-proxy.py logic)
# ---------------------------------------------------------------------------
def _extract_article_text(data):
    """Extract plain text from a QTI stimulus JSON response."""
    if not isinstance(data, dict):
        return ""

    # 1. qti-assessment-stimulus → qti-stimulus-body
    stim = data.get("qti-assessment-stimulus")
    if isinstance(stim, dict):
        body = stim.get("qti-stimulus-body", {})
        r = _render_node_text(body)
        if r and r.strip():
            return r.strip()

    # 2. Nested content wrapper
    content = data.get("content")
    if isinstance(content, dict):
        s2 = content.get("qti-assessment-stimulus")
        if isinstance(s2, dict):
            r = _render_node_text(s2.get("qti-stimulus-body", {}))
            if r and r.strip():
                return r.strip()

    # 3. Direct qti-stimulus-body
    sb = data.get("qti-stimulus-body")
    if sb:
        r = _render_node_text(sb)
        if r and r.strip():
            return r.strip()

    # 4. Simple body/content/html/text fields
    for f in ("body", "content", "html", "text"):
        v = data.get(f)
        if isinstance(v, str) and len(v.strip()) > 10:
            return _extract_html_text(v)
        if isinstance(v, dict):
            r = _render_node_text(v)
            if r and r.strip():
                return r.strip()

    # 5. Nested data wrapper
    inner = data.get("data")
    if isinstance(inner, dict):
        return _extract_article_text(inner)

    return ""


def _render_node_text(node):
    """Convert a QTI JSON node tree to plain text."""
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


def _fetch_article_content(url, res_id, qti_headers):
    """Fetch article/stimulus content and return plain text."""
    stim_id = ""
    if url and "stimuli" in url.lower():
        m = re.search(r"/stimuli/([^/?#]+)", url)
        if m:
            stim_id = m.group(1).strip("/")
    if not stim_id and res_id:
        stim_id = res_id

    # Try QTI stimulus endpoints
    if stim_id:
        for endpoint in [
            f"{QTI_BASE}/api/stimuli/{stim_id}",
            f"{API_BASE}/api/v1/qti/stimuli/{stim_id}/",
        ]:
            resp, ct = _fetch_raw(endpoint, qti_headers)
            if resp:
                ct_lower = (ct or "").lower()
                if "json" in ct_lower:
                    try:
                        text = _extract_article_text(resp.json())
                        if text:
                            return text
                    except Exception:
                        pass
                else:
                    raw = resp.text or ""
                    if raw.strip():
                        return _extract_html_text(raw)

    # Fallback: fetch URL directly
    if url:
        resp, ct = _fetch_raw(url, qti_headers)
        if resp:
            ct_lower = (ct or "").lower()
            if "json" in ct_lower:
                try:
                    text = _extract_article_text(resp.json())
                    if text:
                        return text
                except Exception:
                    pass
            else:
                raw = resp.text or ""
                if raw.strip():
                    return _extract_html_text(raw)

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


def _extract_html_text(raw_xml):
    """Strip HTML/XML tags to get plain question text."""
    if not raw_xml:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_xml)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_qti_item(item):
    """Parse a QTI assessment-item into a simplified question dict."""
    if not isinstance(item, dict):
        return None

    qid = item.get("identifier") or item.get("id") or ""
    title = item.get("title") or ""
    q_type = "mcq"
    prompt_text = ""
    choices = []
    correct_id = ""

    # Try to extract from content.rawXml (PowerPath-style)
    content = item.get("content", {})
    raw_xml = ""
    if isinstance(content, dict):
        raw_xml = content.get("rawXml", "")
    elif isinstance(content, str):
        raw_xml = content

    # Also check for qti-assessment-item wrapper
    qai = item.get("qti-assessment-item", item)
    if isinstance(qai, dict):
        body = qai.get("qti-item-body", {})
        if isinstance(body, dict):
            # Choice interaction (MCQ)
            ci = body.get("qti-choice-interaction", {})
            if ci:
                if isinstance(ci, list):
                    ci = ci[0] if ci else {}
                prompt = ci.get("qti-prompt", "")
                if isinstance(prompt, dict):
                    prompt = prompt.get("#text", "") or prompt.get("_text", "")
                prompt_text = _extract_html_text(str(prompt)) if prompt else ""

                simple_choices = ci.get("qti-simple-choice", [])
                if not isinstance(simple_choices, list):
                    simple_choices = [simple_choices]
                for sc in simple_choices:
                    if isinstance(sc, dict):
                        cid = (sc.get("_attributes") or sc).get("identifier", "")
                        clabel = sc.get("#text", "") or sc.get("_text", "") or _extract_html_text(str(sc))
                        choices.append({"id": cid, "label": clabel})
                    elif isinstance(sc, str):
                        choices.append({"id": sc, "label": sc})

            # Extended text (FRQ)
            eti = body.get("qti-extended-text-interaction", {})
            if eti:
                q_type = "frq"
                prompt = body.get("qti-prompt", "") or (eti.get("qti-prompt", "") if isinstance(eti, dict) else "")
                if isinstance(prompt, dict):
                    prompt = prompt.get("#text", "") or prompt.get("_text", "")
                prompt_text = _extract_html_text(str(prompt)) if prompt else ""

        # Correct answer
        rd = qai.get("qti-response-declaration", qai.get("responseDeclaration", {}))
        if isinstance(rd, dict):
            cr = rd.get("qti-correct-response", rd.get("correctResponse", {}))
            if isinstance(cr, dict):
                val = cr.get("qti-value", cr.get("value", ""))
                if isinstance(val, dict):
                    val = val.get("#text", "") or val.get("_text", "")
                if isinstance(val, list):
                    val = val[0] if val else ""
                correct_id = str(val)

    # Fallback: extract from rawXml
    if not prompt_text and raw_xml:
        prompt_match = re.search(r"<qti-prompt>(.*?)</qti-prompt>", raw_xml, re.DOTALL)
        if prompt_match:
            prompt_text = _extract_html_text(prompt_match.group(1))
        else:
            prompt_text = _extract_html_text(raw_xml)[:500]

    if not correct_id and raw_xml:
        cm = re.search(r"<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>", raw_xml)
        if cm:
            correct_id = cm.group(1)

    if not choices and raw_xml:
        for m in re.finditer(
            r'<qti-simple-choice\s+identifier="([^"]+)"[^>]*>(.*?)</qti-simple-choice>',
            raw_xml,
            re.DOTALL,
        ):
            choices.append({"id": m.group(1), "label": _extract_html_text(m.group(2))})

    if raw_xml and "qti-extended-text-interaction" in raw_xml:
        q_type = "frq"

    if not prompt_text and not choices and not title:
        return None

    result = {
        "id": qid,
        "title": title,
        "prompt": prompt_text,
        "type": q_type,
    }
    if choices:
        result["choices"] = choices
    if correct_id:
        result["correctAnswer"] = correct_id

    # Attach stimulus if present
    stim = item.get("_sectionStimulus")
    if stim and isinstance(stim, dict):
        stim_body = stim.get("qti-assessment-stimulus", stim)
        if isinstance(stim_body, dict):
            stim_content = stim_body.get("qti-stimulus-body", "")
            if stim_content:
                result["stimulus"] = _extract_html_text(str(stim_content))

    return result


# ---------------------------------------------------------------------------
# QTI question resolution (mirrors qti-item.py logic)
# ---------------------------------------------------------------------------
def _resolve_questions_from_test(test, headers):
    """Walk QTI test parts/sections → item refs → fetch items in parallel."""
    parts = test.get("qti-test-part", test.get("testParts", []))
    if not isinstance(parts, list):
        parts = [parts]

    item_hrefs = []
    for part in parts:
        sections = part.get("qti-assessment-section", part.get("sections", []))
        if not isinstance(sections, list):
            sections = [sections]
        for section in sections:
            refs = section.get(
                "qti-assessment-item-ref",
                section.get("itemRefs", section.get("items", [])),
            )
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

    items = []
    if not item_hrefs:
        return items

    def _get(url):
        return url, _fetch(url, headers)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_get, h) for h in item_hrefs]
        ordered = {}
        for f in as_completed(futures):
            try:
                url, (data, _st) = f.result()
                if data:
                    ordered[url] = data
            except Exception:
                pass

    for href in item_hrefs:
        item = ordered.get(href)
        if item:
            items.append(item)
    return items


def _fetch_questions_for_resource(resource, pp_headers, qti_headers):
    """Given a lesson componentResource, try to fetch its QTI questions.

    Returns a list of simplified question dicts.
    """
    res = resource.get("resource", resource) if isinstance(resource, dict) else resource
    if not isinstance(res, dict):
        return []

    meta = res.get("metadata") or {}
    url = meta.get("url", "") or res.get("url", "")
    res_id = res.get("id", "") or res.get("sourcedId", "")

    questions_raw = []

    # Strategy 1: Direct QTI URL from metadata
    if url:
        data, st = _fetch(url, qti_headers)
        if data and isinstance(data, dict):
            test = data.get("qti-assessment-test", data)
            if isinstance(test, dict) and (test.get("qti-test-part") or test.get("testParts")):
                questions_raw = _resolve_questions_from_test(test, qti_headers)
            elif data.get("questions"):
                questions_raw = data["questions"]

    # Strategy 2: Try QTI test by resource ID
    if not questions_raw and res_id:
        all_ids = [res_id] + _resolve_bank_to_qti(res_id)
        for tid in all_ids:
            for endpoint in ["assessment-tests", "assessment-items"]:
                data, st = _fetch(f"{QTI_BASE}/api/{endpoint}/{tid}", qti_headers)
                if data and isinstance(data, dict):
                    test = data.get("qti-assessment-test", data)
                    if isinstance(test, dict) and (test.get("qti-test-part") or test.get("testParts")):
                        questions_raw = _resolve_questions_from_test(test, qti_headers)
                        break
                    if data.get("questions"):
                        questions_raw = data["questions"]
                        break
            if questions_raw:
                break

    # Strategy 3: PowerPath item details
    if not questions_raw and res_id:
        for path in [
            f"{API_BASE}/api/v1/old-powerpath/fetch-item-details/?item_id={res_id}",
            f"{API_BASE}/powerpath/items/{res_id}",
        ]:
            data, st = _fetch(path, pp_headers)
            if data and isinstance(data, dict):
                qs = data.get("questions", data.get("items", []))
                if qs:
                    questions_raw = qs
                    break

    # Parse into simplified format
    parsed = []
    for q in questions_raw:
        p = _parse_qti_item(q)
        if p:
            parsed.append(p)
    return parsed


# ---------------------------------------------------------------------------
# Handler
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
        user_id = params.get("userId", "").strip()

        if not course_id:
            send_json(self, {"error": "Need courseId"}, 400)
            return

        try:
            pp_headers = api_headers()
            qti_headers = _qti_headers()

            tree = None

            # 1a. Try student-specific lesson plan (most reliable, needs userId)
            if user_id:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/{course_id}/{user_id}",
                        headers=pp_headers,
                        timeout=30,
                    )
                    if resp.status_code == 401:
                        pp_headers = api_headers()
                        resp = requests.get(
                            f"{API_BASE}/powerpath/lessonPlans/{course_id}/{user_id}",
                            headers=pp_headers,
                            timeout=30,
                        )
                    if resp.status_code == 200:
                        tree = resp.json()
                except Exception:
                    pass

            # 1b. Fallback: full lesson plan tree (no userId needed)
            if not tree:
                try:
                    resp = requests.get(
                        f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}",
                        headers=pp_headers,
                        timeout=30,
                    )
                    if resp.status_code == 401:
                        pp_headers = api_headers()
                        resp = requests.get(
                            f"{API_BASE}/powerpath/lessonPlans/tree/{course_id}",
                            headers=pp_headers,
                            timeout=30,
                        )
                    if resp.status_code == 200:
                        tree = resp.json()
                except Exception:
                    pass

            if not tree:
                send_json(
                    self,
                    {"error": f"No lesson plan found for course {course_id}", "success": False},
                    404,
                )
                return
            inner = tree.get("lessonPlan", tree) if isinstance(tree, dict) else tree
            if isinstance(inner, dict) and inner.get("lessonPlan"):
                inner = inner["lessonPlan"]

            course_title = inner.get("title", "") if isinstance(inner, dict) else ""
            units_raw = (inner.get("subComponents", []) if isinstance(inner, dict) else [])
            units_raw.sort(key=lambda u: u.get("sortOrder", ""))

            # 2. Walk tree: units → lessons → resources → videos/articles/questions
            units_out = []
            total_questions = 0
            total_videos = 0
            total_articles = 0

            for unit in units_raw:
                unit_title = unit.get("title", "")
                lessons_raw = unit.get("subComponents", [])
                lessons_raw.sort(key=lambda l: l.get("sortOrder", ""))

                # Filter out Advanced Organizer items
                lessons_raw = [
                    les for les in lessons_raw
                    if "advanced organizer" not in (les.get("title", "")).lower()
                    and "organizer submission" not in (les.get("title", "")).lower()
                ]

                # Also create synthetic lessons from unit-level resources if no sub-lessons
                unit_res = unit.get("componentResources", [])
                if not lessons_raw and unit_res:
                    for i, ur in enumerate(unit_res):
                        r = ur.get("resource", ur) if isinstance(ur, dict) else ur
                        lessons_raw.append({
                            "title": (r.get("title", "") if isinstance(r, dict) else "") or f"Assessment {i + 1}",
                            "sortOrder": str(i),
                            "componentResources": [ur],
                        })

                lessons_out = []
                for lesson in lessons_raw:
                    lesson_title = lesson.get("title", "")
                    resources = lesson.get("componentResources", [])

                    lesson_questions = []
                    lesson_videos = []
                    lesson_articles = []

                    for res_wrapper in resources:
                        res = res_wrapper.get("resource", res_wrapper) if isinstance(res_wrapper, dict) else res_wrapper
                        if not isinstance(res, dict):
                            continue

                        meta = res.get("metadata") or {}
                        rurl = meta.get("url", "") or res.get("url", "") or meta.get("href", "") or res.get("href", "")
                        res_id = res.get("id", "") or res.get("sourcedId", "") or (res_wrapper.get("id", "") if isinstance(res_wrapper, dict) else "")
                        res_title = res.get("title", "")
                        kind = _classify_resource(res)

                        if kind == "video":
                            lesson_videos.append({
                                "title": res_title,
                                "url": rurl,
                                "id": res_id,
                            })

                        elif kind == "article":
                            article_text = _fetch_article_content(rurl, res_id, qti_headers)
                            lesson_articles.append({
                                "title": res_title,
                                "url": rurl,
                                "id": res_id,
                                "content": article_text[:5000] if article_text else "",
                            })

                        else:  # assessment
                            qs = _fetch_questions_for_resource(res_wrapper, pp_headers, qti_headers)
                            lesson_questions.extend(qs)

                    total_questions += len(lesson_questions)
                    total_videos += len(lesson_videos)
                    total_articles += len(lesson_articles)

                    lesson_data = {
                        "title": lesson_title,
                        "sortOrder": lesson.get("sortOrder", ""),
                        "questionCount": len(lesson_questions),
                        "questions": lesson_questions,
                    }
                    if lesson_videos:
                        lesson_data["videos"] = lesson_videos
                        lesson_data["videoCount"] = len(lesson_videos)
                    if lesson_articles:
                        lesson_data["articles"] = lesson_articles
                        lesson_data["articleCount"] = len(lesson_articles)
                    lessons_out.append(lesson_data)

                units_out.append({
                    "title": unit_title,
                    "sortOrder": unit.get("sortOrder", ""),
                    "lessonCount": len(lessons_out),
                    "lessons": lessons_out,
                })

            send_json(self, {
                "success": True,
                "course": {"title": course_title, "courseId": course_id},
                "totalQuestions": total_questions,
                "totalVideos": total_videos,
                "totalArticles": total_articles,
                "unitCount": len(units_out),
                "units": units_out,
            })

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
