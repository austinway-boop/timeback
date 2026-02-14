"""GET /api/pp-get-questions-admin?lessonId=...&courseId=...&url=... — Fetch questions for admin.

Tries multiple approaches to get questions:
1. If a QTI URL is provided, fetch directly from QTI
2. Try PowerPath getAssessmentProgress with service account
3. Transform bank ID to QTI test ID and fetch from QTI API

Uses the staging/service account internally. Auto-enrolls if needed.
"""

import json
import re
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, CLIENT_ID, CLIENT_SECRET, api_headers, send_json, get_query_params, get_token

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"
SERVICE_USER_ID = "8ea2b8e1-1b04-4cab-b608-9ab524c059c2"


# ── Auth ─────────────────────────────────────────────────────────────

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


# ── QTI XML parsing ──────────────────────────────────────────────────

def _extract_from_qti_xml(raw_xml: str) -> dict:
    """Parse QTI XML to extract prompt, choices, and correct answer."""
    result = {"prompt": "", "choices": [], "correctId": "", "stimulus": ""}
    if not raw_xml:
        return result

    prompt_match = re.search(r'<qti-prompt[^>]*>(.*?)</qti-prompt>', raw_xml, re.DOTALL)
    if prompt_match:
        result["prompt"] = _strip_html(prompt_match.group(1))

    for m in re.finditer(r'<qti-simple-choice\s+[^>]*identifier="([^"]+)"[^>]*>(.*?)</qti-simple-choice>', raw_xml, re.DOTALL):
        choice_text = re.sub(r'<qti-feedback-inline[^>]*>.*?</qti-feedback-inline>', '', m.group(2), flags=re.DOTALL)
        choice_text = _strip_html(choice_text).strip()
        if choice_text:
            result["choices"].append({"id": m.group(1), "text": choice_text})

    correct_match = re.search(r'<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>', raw_xml)
    if correct_match:
        result["correctId"] = correct_match.group(1).strip()

    stim_match = re.search(r'<qti-stimulus-body[^>]*>(.*?)</qti-stimulus-body>', raw_xml, re.DOTALL)
    if stim_match:
        result["stimulus"] = _strip_html(stim_match.group(1))[:4000]

    return result


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html)
    for ent, rep in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&nbsp;', ' '), ('&quot;', '"')]:
        text = text.replace(ent, rep)
    text = re.sub(r'&#\d+;', '', text)
    return re.sub(r'\s+', ' ', text).strip()


# ── Bank ID → QTI ID transformation ─────────────────────────────────

def _resolve_bank_to_qti(bank_id: str) -> list[str]:
    """Transform a PowerPath bank/resource ID to possible QTI test IDs."""
    ids = []
    if "-bank-" in bank_id:
        ids.append(re.sub(r'-r(\d+)-bank-', r'-qti\1-test-', bank_id))
        ids.append(bank_id.replace("-bank-", "-test-"))
        ids.append(bank_id.replace("-bank-", "-"))
    elif "-r" in bank_id:
        ids.append(re.sub(r'-r(\d+)-', r'-qti\1-', bank_id))
    return ids


# ── Question fetching approaches ─────────────────────────────────────

def _try_qti_url(url: str) -> list[dict]:
    """Approach 1: Fetch questions directly from a QTI URL."""
    if not url:
        return []
    try:
        headers = _qti_headers()
        data, st = _fetch_json(url, headers)
        if not data:
            return []
        return _parse_qti_response(data, headers)
    except Exception:
        return []


def _try_powerpath(lesson_id: str, course_id: str) -> list[dict]:
    """Approach 2: Fetch via PowerPath getAssessmentProgress."""
    if not lesson_id:
        return []
    try:
        headers = api_headers()
        resp = requests.get(
            f"{API_BASE}/powerpath/getAssessmentProgress",
            headers=headers,
            params={"student": SERVICE_USER_ID, "lesson": lesson_id},
            timeout=20,
        )
        if resp.status_code == 404 and course_id:
            # Try enrolling and retrying
            try:
                requests.post(
                    f"{API_BASE}/edubridge/enrollments/enroll/{SERVICE_USER_ID}/{course_id}",
                    headers=headers, json={"role": "student"}, timeout=15,
                )
            except Exception:
                pass
            headers = api_headers()
            resp = requests.get(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers,
                params={"student": SERVICE_USER_ID, "lesson": lesson_id},
                timeout=20,
            )
        if resp.status_code != 200:
            return []
        progress = resp.json()
        raw_questions = progress.get("questions", [])
        parsed = []
        for q in raw_questions:
            qid = q.get("id") or q.get("sourcedId") or ""
            title = q.get("title") or ""
            raw_xml = (q.get("content") or {}).get("rawXml", "")
            extracted = _extract_from_qti_xml(raw_xml)
            parsed.append({
                "identifier": qid, "id": qid, "title": title,
                "prompt": extracted["prompt"] or title,
                "choices": extracted["choices"],
                "correctId": extracted["correctId"],
                "stimulus": extracted["stimulus"],
            })
        return parsed
    except Exception:
        return []


def _try_qti_by_id(res_id: str) -> list[dict]:
    """Approach 3: Transform bank ID to QTI test ID and fetch."""
    if not res_id:
        return []
    qti_ids = _resolve_bank_to_qti(res_id)
    all_ids = qti_ids + [res_id]
    headers = _qti_headers()

    for try_id in all_ids:
        for endpoint in ["assessment-tests", "assessment-items"]:
            data, st = _fetch_json(f"{QTI_BASE}/api/{endpoint}/{try_id}", headers)
            if data:
                questions = _parse_qti_response(data, headers)
                if questions:
                    return questions
    return []


# ── QTI response parsing ────────────────────────────────────────────

def _fetch_json(url, headers, timeout=30):
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.json(), 200
    except Exception:
        pass
    return None, 0


def _parse_qti_response(data: dict, headers: dict) -> list[dict]:
    """Parse a QTI assessment-test response into question list."""
    test = data.get("qti-assessment-test", data) if isinstance(data, dict) else data
    if not isinstance(test, dict):
        return []

    # Check if it has test parts → resolve questions from refs
    if test.get("qti-test-part") or test.get("testParts"):
        return _resolve_questions_from_test(test, headers)

    # Single item
    questions = data.get("questions", data.get("items", []))
    if isinstance(questions, list) and questions:
        return _normalize_questions(questions)

    return []


def _resolve_questions_from_test(test: dict, headers: dict) -> list[dict]:
    """Resolve all questions from a QTI test structure (test parts → sections → items)."""
    item_refs = []
    stimulus_ids = {}

    # Extract item references from test parts
    parts = test.get("qti-test-part") or test.get("testParts") or []
    if isinstance(parts, dict):
        parts = [parts]

    for part in parts:
        if not isinstance(part, dict):
            continue
        sections = part.get("qti-assessment-section") or part.get("sections") or []
        if isinstance(sections, dict):
            sections = [sections]
        for section in sections:
            if not isinstance(section, dict):
                continue
            # Check for stimulus reference in section
            stim_ref = section.get("qti-assessment-stimulus-ref") or {}
            stim_href = ""
            if isinstance(stim_ref, dict):
                stim_href = stim_ref.get("_attributes", {}).get("href", "") or stim_ref.get("href", "")
            elif isinstance(stim_ref, list) and stim_ref:
                stim_href = (stim_ref[0].get("_attributes", {}).get("href", "") or stim_ref[0].get("href", "")) if isinstance(stim_ref[0], dict) else ""

            items = section.get("qti-assessment-item-ref") or section.get("items") or []
            if isinstance(items, dict):
                items = [items]
            for item in items:
                if isinstance(item, dict):
                    href = (item.get("_attributes") or {}).get("href", "") or item.get("href", "")
                    iid = (item.get("_attributes") or {}).get("identifier", "") or item.get("identifier", "")
                    if href or iid:
                        item_refs.append({"href": href, "id": iid})
                        if stim_href:
                            stimulus_ids[iid] = stim_href

    # Fetch each item
    questions = []
    for ref in item_refs[:100]:  # Cap at 100 questions per test
        href = ref["href"]
        iid = ref["id"]
        if href:
            url = href if href.startswith("http") else f"{QTI_BASE}/api/assessment-items/{href}"
            data, st = _fetch_json(url, headers)
            if data:
                q = _normalize_single_question(data, iid)
                # Attach stimulus if available
                if iid in stimulus_ids and not q.get("stimulus"):
                    stim_url = stimulus_ids[iid]
                    if not stim_url.startswith("http"):
                        stim_url = f"{QTI_BASE}/api/stimuli/{stim_url}"
                    stim_data, _ = _fetch_json(stim_url, headers)
                    if stim_data:
                        q["stimulus"] = _extract_stimulus_text(stim_data)[:4000]
                questions.append(q)
        elif iid:
            data, st = _fetch_json(f"{QTI_BASE}/api/assessment-items/{iid}", headers)
            if data:
                questions.append(_normalize_single_question(data, iid))

    return questions


def _normalize_single_question(data: dict, fallback_id: str = "") -> dict:
    """Normalize a single QTI item into our standard format."""
    inner = data.get("qti-assessment-item", data) if isinstance(data, dict) else data
    if not isinstance(inner, dict):
        return {"identifier": fallback_id, "id": fallback_id, "prompt": "", "choices": [], "correctId": "", "stimulus": ""}

    attrs = inner.get("_attributes", {})
    qid = attrs.get("identifier", "") or inner.get("identifier", "") or fallback_id
    title = attrs.get("title", "") or inner.get("title", "")

    # Try raw XML first
    raw_xml = inner.get("rawXml", "") or data.get("rawXml", "")
    if raw_xml:
        extracted = _extract_from_qti_xml(raw_xml)
        return {
            "identifier": qid, "id": qid, "title": title,
            "prompt": extracted["prompt"] or title,
            "choices": extracted["choices"],
            "correctId": extracted["correctId"],
            "stimulus": extracted["stimulus"],
        }

    # Parse from JSON structure
    body = inner.get("qti-item-body", {})
    prompt = ""
    if isinstance(body, dict):
        p = body.get("qti-prompt", body.get("prompt", ""))
        prompt = _deep_text(p) if isinstance(p, (dict, list)) else _strip_html(str(p))

    choices = []
    interaction = body.get("qti-choice-interaction", {}) if isinstance(body, dict) else {}
    if isinstance(interaction, dict):
        raw_choices = interaction.get("qti-simple-choice", [])
        if isinstance(raw_choices, dict):
            raw_choices = [raw_choices]
        for c in raw_choices:
            if isinstance(c, dict):
                cid = (c.get("_attributes") or {}).get("identifier", "")
                ctext = _deep_text(c)
                if cid:
                    choices.append({"id": cid, "text": _strip_html(ctext)})

    correct_id = ""
    resp_decl = inner.get("qti-response-declaration", [])
    if isinstance(resp_decl, dict):
        resp_decl = [resp_decl]
    for rd in resp_decl:
        if isinstance(rd, dict):
            cr = rd.get("qti-correct-response", {})
            if isinstance(cr, dict):
                v = cr.get("qti-value", "")
                if isinstance(v, list):
                    v = v[0] if v else ""
                correct_id = str(v)

    return {
        "identifier": qid, "id": qid, "title": title,
        "prompt": prompt or title,
        "choices": choices,
        "correctId": correct_id,
        "stimulus": "",
    }


def _normalize_questions(questions: list) -> list[dict]:
    return [_normalize_single_question(q) for q in questions if isinstance(q, dict)]


def _extract_stimulus_text(data: dict) -> str:
    """Extract text from a QTI stimulus response."""
    if not isinstance(data, dict):
        return ""
    for path_fn in [
        lambda d: (d.get("qti-assessment-stimulus") or {}).get("qti-stimulus-body"),
        lambda d: d.get("qti-stimulus-body"),
        lambda d: d.get("body") or d.get("content") or d.get("text"),
    ]:
        try:
            node = path_fn(data)
            if node:
                return _strip_html(_deep_text(node)) if isinstance(node, (dict, list)) else _strip_html(str(node))
        except Exception:
            pass
    return ""


def _deep_text(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_deep_text(i) for i in obj)
    if isinstance(obj, dict):
        return " ".join(_deep_text(v) for k, v in obj.items() if not k.startswith("_"))
    return ""


# ── Handler ──────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        lesson_id = params.get("lessonId", "").strip()
        course_id = params.get("courseId", "").strip()
        qti_url = params.get("url", "").strip()

        if not lesson_id and not qti_url:
            send_json(self, {"error": "Missing lessonId or url parameter"}, 400)
            return

        questions = []
        source = ""

        # Approach 1: Direct QTI URL (fastest if available)
        if qti_url:
            questions = _try_qti_url(qti_url)
            if questions:
                source = "qti_url"

        # Approach 2: PowerPath getAssessmentProgress
        if not questions and lesson_id:
            questions = _try_powerpath(lesson_id, course_id)
            if questions:
                source = "powerpath"

        # Approach 3: Transform bank ID to QTI test ID
        if not questions and lesson_id:
            questions = _try_qti_by_id(lesson_id)
            if questions:
                source = "qti_bank_transform"

        send_json(self, {
            "success": len(questions) > 0,
            "source": source,
            "data": {
                "title": "Questions",
                "questions": questions,
                "totalQuestions": len(questions),
            },
            **({"error": f"No questions found (lessonId={lesson_id})"} if not questions else {}),
        })
