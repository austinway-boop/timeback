"""POST /api/generate-explanations — Submit explanation generation job.

Receives { courseId, questions: [...] }.
Normalizes questions, chunks them, submits Anthropic Batch with
research-backed wrong-answer explanation prompt.
"""

import json
import math
import os
import time
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import send_json
from api._kv import kv_get, kv_set, kv_delete

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BATCH_URL = "https://api.anthropic.com/v1/messages/batches"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-opus-4-6"
CHUNK_SIZE = 20  # questions per AI request


def _anthropic_headers():
    return {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _normalize_question(q: dict) -> dict:
    """Normalize a question object to a standard shape for the prompt."""
    qid = q.get("identifier") or q.get("id") or ""
    prompt = q.get("prompt") or q.get("title") or q.get("text") or ""

    # Extract prompt from QTI structure if needed
    if not prompt and isinstance(q.get("qti-assessment-item"), dict):
        body = q["qti-assessment-item"].get("qti-item-body", {})
        if isinstance(body, dict):
            p = body.get("qti-prompt", {})
            if isinstance(p, dict):
                prompt = p.get("p", p.get("span", ""))
            elif isinstance(p, str):
                prompt = p

    # Extract choices
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

    # Extract correct answer
    correct_id = q.get("correctId", "")
    if not correct_id and isinstance(q.get("qti-assessment-item"), dict):
        resp_decl = q["qti-assessment-item"].get("qti-response-declaration", [])
        if isinstance(resp_decl, list):
            for rd in resp_decl:
                if isinstance(rd, dict):
                    cr = rd.get("qti-correct-response", {})
                    if isinstance(cr, dict):
                        correct_id = cr.get("qti-value", "")

    # Extract stimulus
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


def _build_explanation_prompt(questions: list[dict]) -> tuple[str, str]:
    """Build the prompt for generating wrong-answer explanations."""
    system_msg = (
        "You are generating student-facing feedback for wrong answers on quiz questions. "
        "This feedback will be shown immediately after a student selects a wrong answer. "
        "Follow these research-backed principles strictly:\n\n"
        "1. NEVER use the words \"Wrong\", \"Incorrect\", \"No\", or any evaluative language. "
        "No grades, no comparisons.\n"
        "2. Each explanation must be exactly 2-3 sentences. A student should be able to read "
        "it in 5 seconds.\n"
        "3. Be response-contingent: address the specific wrong answer the student chose, not "
        "a generic reteach of the whole concept.\n"
        "4. First sentence: acknowledge why the chosen answer seems plausible (\"This looks "
        "right because...\", \"It's easy to think X because...\").\n"
        "5. Next sentence(s): clearly explain why the correct answer is right, in plain "
        "everyday language.\n"
        "6. Tone: a helpful nudge from a knowledgeable friend. The student should finish "
        "reading feeling smarter, not stupid.\n"
        "7. Do NOT restate the question. Do NOT list multiple concepts. Stay focused on the "
        "one specific mistake."
    )

    questions_text = ""
    for i, q in enumerate(questions):
        questions_text += f"\n--- Question {i+1} (ID: {q['id']}) ---\n"
        if q["stimulus"]:
            questions_text += f"Content/Passage: {q['stimulus'][:3000]}\n"
        questions_text += f"Question: {q['prompt']}\n"
        correct_text = ""
        wrong_ids = []
        for c in q["choices"]:
            marker = " [CORRECT]" if c["id"] == q["correctId"] else ""
            questions_text += f"  {c['id']}: {c['text']}{marker}\n"
            if c["id"] == q["correctId"]:
                correct_text = c["text"]
            else:
                wrong_ids.append(c["id"])

    user_msg = f"""Generate student-facing wrong-answer explanations for each question below.

For each question, produce an explanation for EVERY wrong answer choice. Each explanation must:
- Be 2-3 sentences
- Acknowledge why the student's specific choice seemed reasonable
- Redirect to the correct answer with a clear, plain-language reason

**QUESTIONS:**
{questions_text}

**Return ONLY valid JSON in this exact format, nothing else:**
{{
  "questionId1": {{
    "wrongChoiceId1": "Your 2-3 sentence explanation here...",
    "wrongChoiceId2": "Your 2-3 sentence explanation here..."
  }},
  "questionId2": {{
    "wrongChoiceId1": "Your 2-3 sentence explanation here...",
    "wrongChoiceId2": "Your 2-3 sentence explanation here..."
  }}
}}

Use the actual question IDs and choice IDs from above. Only include wrong answer choices (not the correct one)."""

    return system_msg, user_msg


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
        questions = body.get("questions", [])

        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return
        if not questions or not isinstance(questions, list):
            send_json(self, {"error": "No questions provided"}, 400)
            return
        if not ANTHROPIC_API_KEY:
            send_json(self, {"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        # Check for existing job
        existing = kv_get(f"explanation_job:{course_id}")
        if isinstance(existing, dict) and existing.get("status") == "processing":
            send_json(self, {
                "jobId": course_id,
                "batchId": existing.get("batchId", ""),
                "status": "processing",
                "message": "Explanation generation already in progress",
            })
            return

        # Normalize questions
        normalized = [_normalize_question(q) for q in questions]
        normalized = [q for q in normalized if q["id"] and q["prompt"]]
        if not normalized:
            send_json(self, {"error": "No valid questions found after normalization."}, 400)
            return

        # Delete existing explanations (for regeneration)
        kv_delete(f"explanations:{course_id}")

        # Chunk questions and build batch requests
        chunk_count = math.ceil(len(normalized) / CHUNK_SIZE)
        batch_requests = []
        for i in range(chunk_count):
            chunk = normalized[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
            system_msg, user_msg = _build_explanation_prompt(chunk)
            batch_requests.append({
                "custom_id": f"expl-{course_id}-chunk{i}",
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

            kv_set(f"explanation_job:{course_id}", {
                "batchId": batch_id,
                "status": "processing",
                "createdAt": time.time(),
                "chunkCount": chunk_count,
                "questionCount": len(normalized),
                "model": MODEL,
            })

            send_json(self, {
                "jobId": course_id,
                "batchId": batch_id,
                "status": "processing",
                "chunkCount": chunk_count,
                "questionCount": len(normalized),
            })

        except Exception as e:
            send_json(self, {"error": f"Failed to submit batch: {str(e)}"}, 500)
