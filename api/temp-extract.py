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


def _find_raw_xml(item):
    """Recursively find rawXml in a QTI item dict."""
    if not isinstance(item, dict):
        return ""
    # Direct
    for key in ("rawXml", "raw_xml", "xml"):
        if isinstance(item.get(key), str) and item[key].strip():
            return item[key]
    # Nested in content
    content = item.get("content")
    if isinstance(content, dict):
        for key in ("rawXml", "raw_xml", "xml"):
            if isinstance(content.get(key), str) and content[key].strip():
                return content[key]
    elif isinstance(content, str) and "<" in content:
        return content
    return ""


def _deep_text(obj):
    """Recursively extract all text from a nested dict/list (for fallback)."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_deep_text(i) for i in obj)
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            parts.append(_deep_text(v))
        return " ".join(p for p in parts if p.strip())
    return ""


def _parse_qti_item(item):
    """Parse a QTI assessment-item into a simplified question dict.

    Strategy:
      1. Always extract from rawXml first (regex — most reliable)
      2. Fall back to JSON structure parsing
      3. Last resort: dump all text content from the item
    """
    if not isinstance(item, dict):
        return None

    qid = item.get("identifier") or item.get("id") or ""
    title = item.get("title") or item.get("name") or ""
    q_type = "mcq"
    prompt_text = ""
    choices = []
    correct_id = ""

    # ── 1. Extract from rawXml (most reliable) ──────────────────────
    raw_xml = _find_raw_xml(item)

    if raw_xml:
        # Prompt: try qti-prompt first, then qti-item-body
        pm = re.search(r"<qti-prompt[^>]*>(.*?)</qti-prompt>", raw_xml, re.DOTALL)
        if pm:
            prompt_text = _extract_html_text(pm.group(1))
        else:
            bm = re.search(r"<qti-item-body[^>]*>(.*?)</qti-item-body>", raw_xml, re.DOTALL)
            if bm:
                prompt_text = _extract_html_text(bm.group(1))[:1000]

        # Choices
        for m in re.finditer(
            r'<qti-simple-choice[^>]*identifier="([^"]*)"[^>]*>(.*?)</qti-simple-choice>',
            raw_xml, re.DOTALL,
        ):
            choices.append({"id": m.group(1), "label": _extract_html_text(m.group(2))})
        # Also try without identifier attr (some QTI uses value= instead)
        if not choices:
            for m in re.finditer(
                r"<qti-simple-choice[^>]*>(.*?)</qti-simple-choice>",
                raw_xml, re.DOTALL,
            ):
                label = _extract_html_text(m.group(1))
                if label:
                    choices.append({"id": chr(65 + len(choices)), "label": label})

        # Correct answer
        cm = re.search(r"<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>", raw_xml)
        if cm:
            correct_id = cm.group(1).strip()

        # FRQ detection
        if "qti-extended-text-interaction" in raw_xml:
            q_type = "frq"

    # ── 2. JSON structure parsing (fallback) ────────────────────────
    if not prompt_text or not choices:
        # Walk the item looking for known QTI JSON structures
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
                            p = p.get("#text", "") or p.get("_text", "") or _deep_text(p)
                        if p:
                            prompt_text = _extract_html_text(str(p))
                    if not choices:
                        scs = ci.get("qti-simple-choice", [])
                        if not isinstance(scs, list):
                            scs = [scs]
                        for sc in scs:
                            if isinstance(sc, dict):
                                cid = (sc.get("_attributes") or sc).get("identifier", "")
                                clabel = sc.get("#text", "") or sc.get("_text", "") or _deep_text(sc)
                                clabel = _extract_html_text(clabel)
                                if cid or clabel:
                                    choices.append({"id": cid or chr(65 + len(choices)), "label": clabel})

                eti = body.get("qti-extended-text-interaction")
                if eti:
                    q_type = "frq"
                    if not prompt_text:
                        p = body.get("qti-prompt", "") or (eti.get("qti-prompt", "") if isinstance(eti, dict) else "")
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

    # ── 3. Last resort: extract all text from the item ──────────────
    if not prompt_text:
        all_text = _deep_text(item)
        all_text = _extract_html_text(all_text)
        if len(all_text) > 20:
            prompt_text = all_text[:1500]

    # Skip completely empty items
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
    # Include rawXml snippet for debugging/completeness
    if raw_xml and not prompt_text:
        result["rawContent"] = _extract_html_text(raw_xml)[:2000]

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
# PowerPath question fetching (same endpoint the lesson page uses)
# ---------------------------------------------------------------------------
def _fetch_questions_powerpath(student_id, lesson_id, pp_headers):
    """Fetch questions via getAssessmentProgress — the exact same call
    the lesson page makes.  If the question bank is empty, calls
    resetAttempt to initialize it first (same as quiz-session.py).
    Returns the raw question list from PowerPath.
    """
    def _get_progress():
        try:
            resp = requests.get(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=pp_headers,
                params={"student": student_id, "lesson": lesson_id},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    # 1. Try fetching existing progress
    data = _get_progress()
    if data:
        questions = data.get("questions", [])
        if len(questions) > 0:
            return questions

    # 2. Question bank is empty — initialize it with resetAttempt
    #    (same as quiz-session.py _handle_start when total_q == 0)
    try:
        requests.post(
            f"{API_BASE}/powerpath/resetAttempt",
            headers=pp_headers,
            json={"student": student_id, "lesson": lesson_id},
            timeout=10,
        )
    except Exception:
        pass

    # 3. Fetch again after initialization
    data = _get_progress()
    if data:
        return data.get("questions", [])

    return []


def _parse_powerpath_question(q):
    """Parse a PowerPath question (from getAssessmentProgress) into a
    simplified dict.  Uses rawXml which is the proven extraction path."""
    if not isinstance(q, dict):
        return None

    qid = q.get("id", "")
    title = q.get("title", "")
    raw_xml = ""
    content = q.get("content")
    if isinstance(content, dict):
        raw_xml = content.get("rawXml", "")
    elif isinstance(content, str):
        raw_xml = content

    prompt_text = ""
    choices = []
    correct_id = ""
    q_type = "mcq"

    if raw_xml:
        # Prompt
        pm = re.search(r"<qti-prompt[^>]*>(.*?)</qti-prompt>", raw_xml, re.DOTALL)
        if pm:
            prompt_text = _extract_html_text(pm.group(1))
        if not prompt_text:
            bm = re.search(r"<qti-item-body[^>]*>(.*?)</qti-item-body>", raw_xml, re.DOTALL)
            if bm:
                # Strip out the choice interaction to get just the prompt
                body_html = bm.group(1)
                body_html = re.sub(r"<qti-choice-interaction.*?</qti-choice-interaction>", "", body_html, flags=re.DOTALL)
                body_html = re.sub(r"<qti-extended-text-interaction[^>]*/>", "", body_html)
                prompt_text = _extract_html_text(body_html).strip()

        # Choices
        for m in re.finditer(
            r'<qti-simple-choice[^>]*identifier="([^"]*)"[^>]*>(.*?)</qti-simple-choice>',
            raw_xml, re.DOTALL,
        ):
            choices.append({"id": m.group(1), "label": _extract_html_text(m.group(2))})

        # Correct answer
        cm = re.search(r"<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>", raw_xml)
        if cm:
            correct_id = cm.group(1).strip()

        # FRQ
        if "qti-extended-text-interaction" in raw_xml:
            q_type = "frq"

    # If no rawXml, use title as fallback
    if not prompt_text and not choices:
        prompt_text = title or ""

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
    return result


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
                        res_id = res.get("id", "") or res.get("sourcedId", "") or ""
                        # componentResId: same ID the lesson page uses for PowerPath
                        component_res_id = (
                            (res_wrapper.get("sourcedId", "") if isinstance(res_wrapper, dict) else "")
                            or (res_wrapper.get("id", "") if isinstance(res_wrapper, dict) else "")
                            or res_id
                        )
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
                            # Use getAssessmentProgress — the exact same
                            # endpoint the lesson page uses to load questions.
                            if user_id and component_res_id:
                                raw_qs = _fetch_questions_powerpath(user_id, component_res_id, pp_headers)
                                for rq in raw_qs:
                                    parsed = _parse_powerpath_question(rq)
                                    if parsed:
                                        lesson_questions.append(parsed)

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
