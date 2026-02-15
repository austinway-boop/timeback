"""POST /api/analyze-relevance — Submit question-relevance analysis batch job.

Receives { courseId, lessons: [{ lessonTitle, videoUrl, articleUrl, questions: [...] }] }.
For each lesson, fetches the video transcript and article content, then uses the
Anthropic Batch API to determine whether each question is actually related to
its lesson's learning content.
"""

import json
import math
import os
import re
import time
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import send_json, get_token, API_BASE, CLIENT_ID, CLIENT_SECRET
from api._kv import kv_get, kv_set, kv_delete

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BATCH_URL = "https://api.anthropic.com/v1/messages/batches"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-opus-4-6"
CHUNK_SIZE = 20  # questions per AI request

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"


def _anthropic_headers():
    return {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


# ── Transcript fetching (mirrors review-report.py) ──────────────────

def _fetch_transcript_text(video_url: str) -> str:
    """Fetch YouTube transcript with KV caching."""
    if not video_url:
        return ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        m = re.search(
            r'(?:[?&]v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
            video_url,
        )
        if not m:
            return ""
        video_id = m.group(1)

        cached = kv_get(f"transcript_cache:{video_id}")
        if isinstance(cached, dict) and cached.get("transcript"):
            return cached["transcript"]

        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id)
        parts = []
        for snippet in transcript:
            text = snippet.text if hasattr(snippet, "text") else str(snippet.get("text", ""))
            if text:
                parts.append(text)
        full_text = " ".join(parts) if parts else ""

        if full_text:
            kv_set(f"transcript_cache:{video_id}", {"transcript": full_text, "videoId": video_id})

        return full_text
    except Exception:
        return ""


# ── Article fetching ─────────────────────────────────────────────────

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


def _strip_html(html: str) -> str:
    """Rough HTML-to-text conversion."""
    if not html:
        return ""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _fetch_article_text(article_url: str) -> str:
    """Fetch article/stimulus content from QTI and return plain text."""
    if not article_url:
        return ""
    try:
        stim_match = re.search(r'/stimuli/([^/?#]+)', article_url)
        if not stim_match:
            return ""
        stim_id = stim_match.group(1).strip("/")
        token = _qti_token()

        for endpoint in [
            f"{QTI_BASE}/api/stimuli/{stim_id}",
            f"{API_BASE}/api/v1/qti/stimuli/{stim_id}/",
        ]:
            try:
                resp = requests.get(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json, text/html, application/xml, */*",
                    },
                    timeout=10,
                )
                if resp.status_code == 200 and resp.text.strip():
                    return _strip_html(resp.text)[:8000]
            except Exception:
                continue
    except Exception:
        pass
    return ""


# ── Question normalisation (mirrors generate-explanations.py) ────────

def _normalize_question(q: dict) -> dict:
    """Normalize a question to a standard shape for the relevance prompt."""
    qid = q.get("identifier") or q.get("id") or ""
    prompt = q.get("prompt") or q.get("title") or q.get("text") or ""

    if not prompt and isinstance(q.get("qti-assessment-item"), dict):
        body = q["qti-assessment-item"].get("qti-item-body", {})
        if isinstance(body, dict):
            p = body.get("qti-prompt", {})
            if isinstance(p, dict):
                prompt = p.get("p", p.get("span", ""))
            elif isinstance(p, str):
                prompt = p

    choices = q.get("choices", [])
    if not choices and isinstance(q.get("qti-assessment-item"), dict):
        body = q["qti-assessment-item"].get("qti-item-body", {})
        if isinstance(body, dict):
            interaction = body.get("qti-choice-interaction", {})
            if isinstance(interaction, dict):
                raw_choices = interaction.get("qti-simple-choice", [])
                if isinstance(raw_choices, list):
                    for c in raw_choices:
                        if isinstance(c, dict):
                            cid = (c.get("_attributes") or {}).get("identifier", "")
                            text = c.get("p", c.get("span", c.get("text", "")))
                            if isinstance(text, dict):
                                text = text.get("p", text.get("span", str(text)))
                            choices.append({"id": cid, "text": str(text)})

    correct_id = q.get("correctId", "")
    if not correct_id and isinstance(q.get("qti-assessment-item"), dict):
        resp_decl = q["qti-assessment-item"].get("qti-response-declaration", [])
        if isinstance(resp_decl, list):
            for rd in resp_decl:
                if isinstance(rd, dict):
                    cr = rd.get("qti-correct-response", {})
                    if isinstance(cr, dict):
                        correct_id = cr.get("qti-value", "")

    stimulus = q.get("stimulus") or q.get("passage") or ""
    if not stimulus and isinstance(q.get("_sectionStimulus"), dict):
        stim = q["_sectionStimulus"]
        stim_body = (stim.get("qti-assessment-stimulus") or {}).get("qti-stimulus-body", {})
        if isinstance(stim_body, dict):
            stimulus = json.dumps(stim_body)[:4000]
        elif isinstance(stim_body, str):
            stimulus = stim_body[:4000]

    return {
        "id": qid,
        "prompt": str(prompt)[:2000],
        "choices": choices[:6],
        "correctId": str(correct_id),
        "stimulus": str(stimulus)[:4000],
    }


# ── Prompt building ──────────────────────────────────────────────────

def _build_relevance_prompt(
    questions: list[dict],
    lesson_contents: dict[str, dict],
) -> tuple[str, str]:
    """Build the prompt for analysing question relevance.

    ``lesson_contents`` maps lessonTitle → { "transcript": str, "article": str }.
    Each question dict must include a ``lessonTitle`` key.
    """

    system_msg = (
        "You are an educational content quality analyst for an AP-level learning platform. "
        "Your job is to determine whether each quiz question is actually related to the "
        "learning content of the lesson it belongs to.\n\n"
        "For each question you will receive:\n"
        "- The lesson's video transcript and/or article text (the LEARNING CONTENT)\n"
        "- The question text, answer choices, and any stimulus passage or image description\n\n"
        "ANALYSIS CRITERIA:\n"
        "1. CONTENT COVERAGE: Does the lesson's learning content (video transcript and/or "
        "article) cover the knowledge needed to answer this question? The content does not "
        "need to state the answer verbatim, but the topic/concept must be addressed.\n"
        "2. STIMULUS RELEVANCE: If the question has a stimulus (passage, image, data), is it "
        "thematically connected to the lesson's topic?\n"
        "3. SCOPE: Is the question testing content that is reasonably within the lesson's scope, "
        "even if not explicitly stated word-for-word? Questions that test synthesis or application "
        "of covered concepts are acceptable.\n\n"
        "DEFAULT STANCE: Assume questions are RELEVANT unless the evidence clearly shows "
        "otherwise. Only flag questions that ask about topics or concepts that have NO "
        "connection to the lesson's learning content. Be conservative — when in doubt, mark "
        "the question as relevant.\n\n"
        "CATEGORIES for irrelevant questions:\n"
        "- \"off_topic\": Question is about a completely different topic than the lesson.\n"
        "- \"too_specific\": Question requires knowledge of trivial minutiae not covered in the content.\n"
        "- \"no_source_material\": No learning content was available to verify against.\n\n"
        "Return your analysis as a JSON object. For EACH question, provide:\n"
        "{\n"
        '  "questionId": {\n'
        '    "relevant": true/false,\n'
        '    "confidence": 0-100,\n'
        '    "reasoning": "1-2 sentence explanation",\n'
        '    "category": "good" | "off_topic" | "too_specific" | "no_source_material"\n'
        "  }\n"
        "}\n\n"
        "IMPORTANT: Return ONLY valid JSON. No text outside the JSON object."
    )

    user_msg = "Analyze each question's relevance to its lesson content.\n\n"

    for i, q in enumerate(questions):
        lt = q.get("lessonTitle", "Unknown Lesson")
        lc = lesson_contents.get(lt, {})
        transcript = (lc.get("transcript") or "")[:6000]
        article = (lc.get("article") or "")[:6000]

        user_msg += f"\n--- Question {i + 1} (ID: {q['id']}) ---\n"
        user_msg += f"Lesson: {lt}\n"

        if transcript:
            user_msg += f"Video Transcript (excerpt): {transcript}\n"
        if article:
            user_msg += f"Article Content (excerpt): {article}\n"
        if not transcript and not article:
            user_msg += "(No learning content available for this lesson.)\n"

        if q.get("stimulus"):
            user_msg += f"Question Stimulus: {q['stimulus'][:3000]}\n"
        user_msg += f"Question: {q['prompt']}\n"
        for c in q.get("choices", []):
            marker = " [CORRECT]" if c["id"] == q.get("correctId") else ""
            user_msg += f"  {c['id']}: {c['text']}{marker}\n"

    user_msg += (
        "\n**Return ONLY valid JSON mapping each question ID to its analysis.**\n"
        "Use the actual question IDs from above as keys."
    )

    return system_msg, user_msg


# ── Handler ──────────────────────────────────────────────────────────

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
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        course_id = body.get("courseId", "").strip()
        lessons = body.get("lessons", [])

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return
        if not lessons or not isinstance(lessons, list):
            send_json(self, {"error": "No lessons provided"}, 400)
            return
        if not ANTHROPIC_API_KEY:
            send_json(self, {"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        # Check for existing job
        existing = kv_get(f"relevance_job:{course_id}")
        if isinstance(existing, dict) and existing.get("status") == "processing":
            send_json(self, {
                "jobId": course_id,
                "batchId": existing.get("batchId", ""),
                "status": "processing",
                "message": "Relevance analysis already in progress",
            })
            return

        # Fetch lesson content (transcripts + articles)
        lesson_contents: dict[str, dict] = {}
        for lesson in lessons:
            lt = lesson.get("lessonTitle", "")
            if lt in lesson_contents:
                continue
            transcript = _fetch_transcript_text(lesson.get("videoUrl", ""))
            article = _fetch_article_text(lesson.get("articleUrl", ""))
            lesson_contents[lt] = {"transcript": transcript, "article": article}

        # Normalize all questions and attach lessonTitle
        all_questions = []
        for lesson in lessons:
            lt = lesson.get("lessonTitle", "")
            for q in lesson.get("questions", []):
                nq = _normalize_question(q)
                if nq["id"] and nq["prompt"]:
                    nq["lessonTitle"] = lt
                    all_questions.append(nq)

        if not all_questions:
            send_json(self, {"error": "No valid questions found after normalization."}, 400)
            return

        # Delete existing analysis (for re-analysis)
        kv_delete(f"relevance_analysis:{course_id}")

        # Chunk questions and build batch requests
        chunk_count = math.ceil(len(all_questions) / CHUNK_SIZE)
        batch_requests = []
        for i in range(chunk_count):
            chunk = all_questions[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
            system_msg, user_msg = _build_relevance_prompt(chunk, lesson_contents)
            batch_requests.append({
                "custom_id": f"rel-{course_id}-chunk{i}",
                "params": {
                    "model": MODEL,
                    "max_tokens": 64000,
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": 10000,
                    },
                    "system": system_msg,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            })

        # Submit batch
        try:
            resp = requests.post(
                ANTHROPIC_BATCH_URL,
                headers=_anthropic_headers(),
                json={"requests": batch_requests},
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                error_detail = ""
                try:
                    error_detail = resp.json().get("error", {}).get("message", resp.text[:300])
                except Exception:
                    error_detail = resp.text[:300]
                send_json(self, {"error": f"Anthropic API error ({resp.status_code}): {error_detail}"}, 500)
                return

            batch_data = resp.json()
            batch_id = batch_data.get("id", "")

            kv_set(f"relevance_job:{course_id}", {
                "batchId": batch_id,
                "status": "processing",
                "createdAt": time.time(),
                "chunkCount": chunk_count,
                "questionCount": len(all_questions),
                "model": MODEL,
            })

            send_json(self, {
                "jobId": course_id,
                "batchId": batch_id,
                "status": "processing",
                "chunkCount": chunk_count,
                "questionCount": len(all_questions),
            })

        except Exception as e:
            send_json(self, {"error": f"Failed to submit batch: {str(e)}"}, 500)
