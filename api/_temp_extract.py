"""GET /api/_temp_extract?courseId=...

TEMPORARY — Extract all questions from an AP course's PowerPath lesson plan tree.

Walks the lesson plan tree (units → lessons → resources) and fetches QTI question
content for every assessment resource.  Returns an organized JSON structure:

  { course: {title, courseId}, units: [ { title, sortOrder, lessons: [ { title, sortOrder, questions: [...] } ] } ] }

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

        if not course_id:
            send_json(self, {"error": "Need courseId"}, 400)
            return

        try:
            pp_headers = api_headers()
            qti_headers = _qti_headers()

            # 1. Fetch lesson plan tree (no userId needed)
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
            if resp.status_code != 200:
                send_json(
                    self,
                    {"error": f"Failed to fetch lesson plan tree ({resp.status_code})", "success": False},
                    502,
                )
                return

            tree = resp.json()
            inner = tree.get("lessonPlan", tree) if isinstance(tree, dict) else tree
            if isinstance(inner, dict) and inner.get("lessonPlan"):
                inner = inner["lessonPlan"]

            course_title = inner.get("title", "") if isinstance(inner, dict) else ""
            units_raw = (inner.get("subComponents", []) if isinstance(inner, dict) else [])
            units_raw.sort(key=lambda u: u.get("sortOrder", ""))

            # 2. Walk tree: units → lessons → resources → questions
            units_out = []
            total_questions = 0

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
                    for res in resources:
                        qs = _fetch_questions_for_resource(res, pp_headers, qti_headers)
                        lesson_questions.extend(qs)

                    total_questions += len(lesson_questions)
                    lessons_out.append({
                        "title": lesson_title,
                        "sortOrder": lesson.get("sortOrder", ""),
                        "questionCount": len(lesson_questions),
                        "questions": lesson_questions,
                    })

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
                "unitCount": len(units_out),
                "units": units_out,
            })

        except Exception as e:
            send_json(self, {"error": str(e), "success": False}, 500)
