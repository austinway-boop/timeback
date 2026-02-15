"""POST /api/review-report — Trigger AI review of a question report.

POST /api/review-report  { "reportId": "rpt_..." }
     → { "verdict": "valid"|"invalid", "pointsAwarded": 5, "reasoning": "..." }

Fetches the report from KV, gets video transcript, builds prompt,
calls Anthropic Claude, stores verdict, and returns result.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler

from api._kv import kv_get, kv_set, kv_list_get, kv_list_push

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# Fallback points for valid report when ppScore >= 80
VALID_REPORT_POINTS = 5


def _pp_score_change(pp_score: float, difficulty: str) -> int:
    """Mirror the client-side stage-based scoring table (correct-answer column).

    When ppScore < 80, a valid report awards the same points as answering
    the question correctly at the student's current stage.
    """
    pp_score = pp_score or 0
    difficulty = (difficulty or "medium").lower()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"

    if pp_score <= 50:
        table = {"easy": 3, "medium": 6, "hard": 9}
    elif pp_score <= 80:
        table = {"easy": 2, "medium": 5, "hard": 8}
    elif pp_score <= 95:
        table = {"easy": 1, "medium": 3, "hard": 5}
    else:
        table = {"easy": 1, "medium": 1, "hard": 3}

    return table[difficulty]


def _strip_html(html: str) -> str:
    """Rough HTML-to-text conversion."""
    if not html:
        return ""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _fetch_transcript_text(video_url: str) -> str:
    """Fetch transcript via our own video-transcript endpoint logic."""
    if not video_url:
        return ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        m = re.search(r'(?:[?&]v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})', video_url)
        if not m:
            return ""
        video_id = m.group(1)

        # Check cache
        cached = kv_get(f"transcript_cache:{video_id}")
        if isinstance(cached, dict) and cached.get("transcript"):
            return cached["transcript"]

        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id)
        parts = []
        for snippet in transcript:
            text = snippet.text if hasattr(snippet, 'text') else str(snippet.get('text', ''))
            if text:
                parts.append(text)
        full_text = " ".join(parts) if parts else ""

        if full_text:
            kv_set(f"transcript_cache:{video_id}", {"transcript": full_text, "videoId": video_id})

        return full_text
    except Exception:
        return ""


def _build_prompt(report: dict, transcript: str, is_human_reviewed: bool) -> list:
    """Build the messages array for the Anthropic API call."""
    article_text = _strip_html(report.get("articleContent", ""))

    # Format choices
    choices_text = ""
    choices = report.get("choices", [])
    for i, c in enumerate(choices):
        label = c.get("label", c.get("text", c.get("value", f"Choice {i+1}")))
        cid = c.get("id", c.get("identifier", ""))
        is_correct = " ✓ CORRECT" if cid == report.get("correctId", "") else ""
        choices_text += f"  {chr(65+i)}. {label}{is_correct}\n"

    # Reason text
    reason_map = {
        "not_in_source": "Question asks for information not in source materials (video/article)",
        "factual_error": "Question contains factual errors",
        "poorly_written": "Question is poorly written/unclear",
        "other": "Other",
    }
    reason = reason_map.get(report.get("reason", ""), report.get("reason", "Unknown"))
    custom = report.get("customText", "")
    if custom:
        reason += f" — Student elaboration: {custom}"

    strictness = ""
    if is_human_reviewed:
        strictness = (
            "\n\nCRITICAL: This question has been previously reviewed by a human administrator "
            "and marked as CORRECT. Apply EXTREMELY strict scrutiny. Only flag this question "
            "as invalid if the evidence is overwhelmingly clear and indisputable. The bar for "
            "overturning a human review is very high."
        )

    system_msg = (
        "You are a rigorous educational content reviewer for an AP-level learning platform. "
        "Your job is to evaluate a student's report that a quiz question is flawed.\n\n"
        "DEFAULT STANCE: Assume questions are VALID unless the evidence clearly proves otherwise. "
        "Students may report questions simply because they got them wrong. You must be objective.\n\n"
        "ANALYSIS CRITERIA:\n"
        "1. HYPER-SPECIFICITY: Is this question testing knowledge that is too obscure or hyper-specific "
        "to be necessary for scoring a 5 on the AP exam? Lean toward the question being acceptable, "
        "but flag if it tests trivial minutiae not reasonably expected on the AP.\n"
        "2. CONTENT RELEVANCE: Is the question actually related to the provided source materials "
        "(video transcript and/or article)? If the question has no connection to the content, it is a bad question.\n"
        "3. ANSWER CORRECTNESS: Is the marked correct answer actually correct based on the source material? "
        "Are there multiple fully defensible answers among the choices? If the correct answer is wrong "
        "or multiple answers are equally defensible, it is a bad question.\n\n"
        "Be thorough. Take your time to reason carefully through each criterion.\n"
        "Return your analysis as JSON with these exact fields:\n"
        '{ "verdict": "valid" or "invalid", "confidence": 0-100, "reasoning": "detailed explanation", '
        '"recommendation": "remove" or "regenerate" or "keep", "is_bad_question": true or false, '
        '"student_summary": "1-2 sentence plain-English summary for the student", '
        '"lesson_relevance": "short explanation of why this question is or isn\'t appropriate for the lesson" }\n\n'
        "- verdict 'valid' means the student's REPORT is valid (the question IS flawed)\n"
        "- verdict 'invalid' means the student's report is invalid (the question is fine)\n"
        "- is_bad_question: true if the question fails any of the 3 criteria above, false otherwise\n"
        "- student_summary: A friendly 1-2 sentence explanation suitable for showing to the student. "
        "For valid reports, explain what was wrong with the question. "
        "For invalid reports, briefly explain why the question is actually correct.\n"
        "- lesson_relevance: A concise explanation of how this question relates (or doesn't) to the "
        "lesson's source material. Admins use this to quickly understand the issue.\n\n"
        "IMPORTANT: You MUST respond with ONLY a valid JSON object. No explanation or text outside the JSON."
        + strictness
    )

    user_msg = "Please review the following reported question:\n\n"

    if transcript:
        # Truncate very long transcripts to ~8000 chars to leave room for reasoning
        t = transcript[:8000] + ("..." if len(transcript) > 8000 else "")
        user_msg += f"=== VIDEO TRANSCRIPT ===\n{t}\n\n"

    if article_text:
        a = article_text[:8000] + ("..." if len(article_text) > 8000 else "")
        user_msg += f"=== ARTICLE CONTENT ===\n{a}\n\n"

    if not transcript and not article_text:
        user_msg += "(No source material was available for this question.)\n\n"

    user_msg += (
        f"=== REPORTED QUESTION ===\n"
        f"{report.get('questionText', 'N/A')}\n\n"
        f"Choices:\n{choices_text}\n"
        f"=== STUDENT'S REASON FOR REPORTING ===\n"
        f"{reason}\n"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _extract_json(text: str) -> dict | None:
    """Extract JSON object containing 'verdict' using balanced-brace parsing.

    Handles cases where the AI reasoning field contains { or } characters,
    which would break a simple regex approach.
    """
    # First, strip markdown code fences if present
    stripped = re.sub(r'```(?:json)?\s*', '', text).strip()
    stripped = re.sub(r'```\s*$', '', stripped).strip()

    # Try direct parse first
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict) and "verdict" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # Balanced-brace extraction: find each top-level { ... } block
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            start = i
            in_string = False
            escape_next = False
            for j in range(i, len(text)):
                ch = text[j]
                if escape_next:
                    escape_next = False
                    continue
                if ch == '\\' and in_string:
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:j + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict) and "verdict" in obj:
                                return obj
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
            i = j + 1 if depth == 0 else i + 1
        else:
            i += 1

    return None


def _call_anthropic(messages: list) -> dict | None:
    """Call Anthropic API and return parsed JSON response."""
    if not ANTHROPIC_API_KEY:
        print("[review-report] ERROR: ANTHROPIC_API_KEY not set")
        return None
    try:
        import requests

        # Anthropic uses a separate system param; extract it from messages
        system_text = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                user_messages.append(m)

        req_body = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 4096,
            "temperature": 0.2,
            "system": system_text,
            "messages": user_messages,
        }

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=req_body,
            timeout=120,
        )
        if resp.status_code != 200:
            print(f"[review-report] Anthropic API error: status={resp.status_code} body={resp.text[:500]}")
            return None
        data = resp.json()
        content = data["content"][0]["text"]
        # Use balanced-brace extractor to handle nested braces in reasoning
        result = _extract_json(content)
        if result:
            return result
        # Fallback: direct parse
        print(f"[review-report] WARNING: _extract_json failed, attempting direct parse. Content preview: {content[:300]}")
        return json.loads(content)
    except Exception as e:
        print(f"[review-report] ERROR in _call_anthropic: {e}")
        return None


def _send_json(handler, data, status=200):
    body = json.dumps(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body.encode())


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            _send_json(self, {"error": "Invalid JSON"}, 400)
            return

        report_id = body.get("reportId", "")
        if not report_id:
            _send_json(self, {"error": "Missing reportId"}, 400)
            return

        # Load report
        report = kv_get(f"report:{report_id}")
        if not isinstance(report, dict):
            _send_json(self, {"error": "Report not found"}, 404)
            return

        # Already resolved?
        if report.get("status") == "resolved":
            _send_json(self, {
                "verdict": report.get("verdict"),
                "pointsAwarded": report.get("pointsAwarded", 0),
                "reasoning": report.get("aiReasoning", ""),
                "alreadyResolved": True,
            })
            return

        # Check human review flags
        question_id = report.get("questionId", "")
        question_flags = kv_get(f"question_flags:{question_id}")
        is_human_reviewed = (
            isinstance(question_flags, dict)
            and question_flags.get("humanReviewCount", 0) >= 1
        )

        # Fetch transcript
        transcript = _fetch_transcript_text(report.get("videoUrl", ""))

        # Build prompt and call AI
        messages = _build_prompt(report, transcript, is_human_reviewed)
        ai_result = _call_anthropic(messages)

        if not ai_result:
            # AI call failed — mark for manual review
            report["status"] = "ai_error"
            report["aiReasoning"] = "AI review failed. Queued for manual admin review."
            kv_set(f"report:{report_id}", report)
            _send_json(self, {
                "verdict": None,
                "pointsAwarded": 0,
                "reasoning": "AI review failed — queued for admin review.",
                "error": True,
            })
            return

        verdict = ai_result.get("verdict", "invalid")
        confidence = ai_result.get("confidence", 50)
        reasoning = ai_result.get("reasoning", "")
        recommendation = ai_result.get("recommendation", "keep")
        is_bad_question = bool(ai_result.get("is_bad_question", False))
        student_summary = ai_result.get("student_summary", "")
        lesson_relevance = ai_result.get("lesson_relevance", "")

        # For human-reviewed questions, require very high confidence to overturn
        if is_human_reviewed and verdict == "valid" and confidence < 90:
            verdict = "invalid"
            is_bad_question = False
            reasoning += " [Overridden: confidence too low to overturn human review]"

        # Only award points if the student got the question WRONG
        answered_correctly = report.get("answeredCorrectly", False)
        if verdict == "valid" and not answered_correctly:
            pp_score = report.get("ppScore", 0)
            difficulty = report.get("difficulty", "medium")
            if pp_score < 80:
                # Before 80%: treat report like a correct answer (stage-based)
                points = _pp_score_change(pp_score, difficulty)
            else:
                points = VALID_REPORT_POINTS
        else:
            points = 0

        # If AI flagged as bad question, temporarily hide from all users
        ai_flagged_bad = False
        if is_bad_question and verdict == "valid":
            ai_flagged_bad = True
            hidden = kv_list_get("globally_hidden_questions")
            if question_id and question_id not in hidden:
                kv_list_push("globally_hidden_questions", question_id)

        # Update report
        if ai_flagged_bad:
            report["status"] = "ai_flagged_bad"
        else:
            report["status"] = "resolved"
        report["verdict"] = verdict
        report["aiReasoning"] = reasoning
        report["aiConfidence"] = confidence
        report["aiRecommendation"] = recommendation
        report["aiFlaggedBad"] = ai_flagged_bad
        report["pointsAwarded"] = points
        report["answeredCorrectly"] = answered_correctly
        report["studentSummary"] = student_summary
        report["aiLessonRelevance"] = lesson_relevance
        kv_set(f"report:{report_id}", report)

        _send_json(self, {
            "verdict": verdict,
            "pointsAwarded": points,
            "reasoning": reasoning,
            "aiFlaggedBad": ai_flagged_bad,
            "studentSummary": student_summary,
            "lessonRelevance": lesson_relevance,
        })
