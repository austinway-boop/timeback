"""GET /api/pp-get-questions-admin?lessonId=...&courseId=... — Fetch full PowerPath questions for admin use.

Uses the staging account internally so no user credentials are needed.
Auto-enrolls the staging account in the course if PowerPath returns 404.
Returns full question data including parsed prompt, choices, and correct answer
extracted from the QTI XML content.
"""

import json
import re
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json, get_query_params

# Staging account sourcedId (pehal64861@aixind.com)
STAGING_STUDENT_ID = "8ea2b8e1-1b04-4cab-b608-9ab524c059c2"
EDUBRIDGE_ENROLL_URL = f"{API_BASE}/edubridge/enrollments/enroll"


def _extract_from_qti_xml(raw_xml: str) -> dict:
    """Parse QTI XML to extract prompt, choices, and correct answer."""
    result = {"prompt": "", "choices": [], "correctId": "", "stimulus": ""}

    if not raw_xml:
        return result

    # Extract prompt text
    prompt_match = re.search(
        r'<qti-prompt[^>]*>(.*?)</qti-prompt>',
        raw_xml, re.DOTALL
    )
    if prompt_match:
        result["prompt"] = _strip_html(prompt_match.group(1))

    # Extract choices
    choice_pattern = re.finditer(
        r'<qti-simple-choice\s+[^>]*identifier="([^"]+)"[^>]*>(.*?)</qti-simple-choice>',
        raw_xml, re.DOTALL
    )
    for m in choice_pattern:
        choice_id = m.group(1)
        choice_text = _strip_html(m.group(2))
        # Remove inline feedback from choice text
        choice_text = re.sub(r'<qti-feedback-inline[^>]*>.*?</qti-feedback-inline>', '', choice_text, flags=re.DOTALL)
        choice_text = _strip_html(choice_text)
        if choice_text.strip():
            result["choices"].append({"id": choice_id, "text": choice_text.strip()})

    # Extract correct answer
    correct_match = re.search(
        r'<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>',
        raw_xml
    )
    if correct_match:
        result["correctId"] = correct_match.group(1).strip()

    # Extract stimulus/passage if embedded
    stim_match = re.search(
        r'<qti-stimulus-body[^>]*>(.*?)</qti-stimulus-body>',
        raw_xml, re.DOTALL
    )
    if stim_match:
        result["stimulus"] = _strip_html(stim_match.group(1))[:4000]

    return result


def _strip_html(html: str) -> str:
    """Remove HTML tags and clean up whitespace."""
    if not html:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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

        if not lesson_id:
            send_json(self, {"error": "Missing lessonId parameter"}, 400)
            return

        headers = api_headers()

        try:
            # Attempt 1: Fetch assessment progress from PowerPath
            resp = _fetch_pp_questions(headers, lesson_id)

            # If 404 and we have a courseId, try auto-enrolling and retrying
            if resp.status_code == 404 and course_id:
                enroll_ok = _enroll_staging_account(headers, course_id)
                if enroll_ok:
                    # Retry after enrollment
                    headers = api_headers()  # refresh token
                    resp = _fetch_pp_questions(headers, lesson_id)

            if resp.status_code != 200:
                send_json(self, {
                    "error": f"PowerPath API returned {resp.status_code} for lesson {lesson_id}",
                    "success": False,
                    "data": {"questions": [], "totalQuestions": 0},
                }, 200)
                return

            progress = resp.json()
            raw_questions = progress.get("questions", [])

            # Parse each question's QTI XML into structured data
            parsed_questions = []
            for q in raw_questions:
                qid = q.get("id") or q.get("sourcedId") or ""
                title = q.get("title") or ""
                raw_xml = (q.get("content") or {}).get("rawXml", "")

                extracted = _extract_from_qti_xml(raw_xml)

                parsed_questions.append({
                    "identifier": qid,
                    "id": qid,
                    "title": title,
                    "prompt": extracted["prompt"] or title,
                    "choices": extracted["choices"],
                    "correctId": extracted["correctId"],
                    "stimulus": extracted["stimulus"],
                })

            send_json(self, {
                "success": True,
                "data": {
                    "title": "PowerPath Lesson Questions",
                    "questions": parsed_questions,
                    "totalQuestions": len(parsed_questions),
                },
            })

        except Exception as e:
            send_json(self, {
                "error": f"Exception: {str(e)} (lesson={lesson_id})",
                "success": False,
                "data": {"questions": [], "totalQuestions": 0},
            }, 200)


def _fetch_pp_questions(headers: dict, lesson_id: str):
    """Fetch assessment progress from PowerPath."""
    return requests.get(
        f"{API_BASE}/powerpath/getAssessmentProgress",
        headers=headers,
        params={"student": STAGING_STUDENT_ID, "lesson": lesson_id},
        timeout=20,
    )


def _enroll_staging_account(headers: dict, course_id: str) -> bool:
    """Auto-enroll the staging account in a course via EduBridge."""
    try:
        resp = requests.post(
            f"{EDUBRIDGE_ENROLL_URL}/{STAGING_STUDENT_ID}/{course_id}",
            headers=headers,
            json={"role": "student"},
            timeout=15,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False
