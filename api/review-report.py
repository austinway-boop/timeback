"""POST /api/review-report — Trigger AI review of a question report.

POST /api/review-report  { "reportId": "rpt_..." }
     → { "verdict": "valid"|"invalid", "pointsAwarded": 5, "reasoning": "..." }

Fetches the report from KV, gets video transcript, builds prompt,
calls GPT-5.2-thinking, stores verdict, and returns result.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler

from _kv import kv_get, kv_set

OPENAI_KEY = os.environ.get("OPEN_AI_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.2-thinking")

# Points awarded for a valid report (same as a correct answer base)
VALID_REPORT_POINTS = 5


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
    """Build the messages array for the OpenAI API call."""
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
        "1. Out-of-scope content: Does the question require knowledge beyond the provided video transcript and/or article?\n"
        "2. Factual accuracy: Are the question and answer choices factually correct based on the source material?\n"
        "3. Question quality: Is the question well-constructed, clear, and unambiguous?\n\n"
        "Be thorough. Take your time to reason carefully through each criterion.\n"
        "Return your analysis as JSON with these exact fields:\n"
        '{ "verdict": "valid" or "invalid", "confidence": 0-100, "reasoning": "detailed explanation", '
        '"recommendation": "remove" or "regenerate" or "keep" }\n\n'
        "- verdict 'valid' means the student's REPORT is valid (the question IS flawed)\n"
        "- verdict 'invalid' means the student's report is invalid (the question is fine)"
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


def _call_openai(messages: list) -> dict | None:
    """Call OpenAI API and return parsed JSON response."""
    if not OPENAI_KEY:
        return None
    try:
        import requests
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": messages,
                "temperature": 0.2,
            },
            timeout=120,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # Extract JSON from response (may be wrapped in markdown code blocks)
        json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return json.loads(content)
    except Exception:
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
        ai_result = _call_openai(messages)

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

        # For human-reviewed questions, require very high confidence to overturn
        if is_human_reviewed and verdict == "valid" and confidence < 90:
            verdict = "invalid"
            reasoning += " [Overridden: confidence too low to overturn human review]"

        points = VALID_REPORT_POINTS if verdict == "valid" else 0

        # Update report
        report["status"] = "resolved"
        report["verdict"] = verdict
        report["aiReasoning"] = reasoning
        report["aiConfidence"] = confidence
        report["aiRecommendation"] = recommendation
        report["pointsAwarded"] = points
        kv_set(f"report:{report_id}", report)

        _send_json(self, {
            "verdict": verdict,
            "pointsAwarded": points,
            "reasoning": reasoning,
        })
