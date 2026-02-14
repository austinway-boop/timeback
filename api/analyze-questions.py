"""POST /api/analyze-questions — Submit question-to-skill analysis job.

Receives { courseId, questions: [...] }.
Saves raw questions to KV, loads skill tree, chunks questions,
submits Anthropic Batch with one request per chunk.
"""

import json
import math
import os
import re
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


def _parse_skill_nodes(mermaid_code: str) -> list[tuple[str, str]]:
    """Extract (nodeId, label) pairs from mermaid code."""
    nodes = {}
    for match in re.finditer(r'(\w+)\["([^"]+)"\]', mermaid_code):
        nid, label = match.group(1), match.group(2)
        if nid not in nodes:
            nodes[nid] = label
    return list(nodes.items())


def _normalize_question(q: dict) -> dict:
    """Normalize a question object to a standard shape for the prompt."""
    # Handle various question formats from QTI
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
            stimulus = json.dumps(stim_body)[:4000]  # Truncate very long stimuli
        elif isinstance(stim_body, str):
            stimulus = stim_body[:4000]

    return {
        "id": qid,
        "prompt": str(prompt)[:2000],
        "choices": choices[:6],  # Max 6 choices
        "correctId": str(correct_id),
        "stimulus": str(stimulus)[:4000],
    }


def _build_chunk_prompt(skill_nodes: list[tuple[str, str]], questions: list[dict]) -> tuple[str, str]:
    """Build the prompt for a chunk of questions."""
    system_msg = (
        "You are an expert AP assessment analyst. Your task is to analyze quiz questions "
        "and determine how each question and its answer choices relate to a course skill tree. "
        "For each wrong answer, explain what misunderstanding or knowledge gap it reveals."
    )

    skill_list = "\n".join(f"  {nid}: {label}" for nid, label in skill_nodes)

    questions_text = ""
    for i, q in enumerate(questions):
        questions_text += f"\n--- Question {i+1} (ID: {q['id']}) ---\n"
        if q["stimulus"]:
            questions_text += f"Content/Passage: {q['stimulus'][:3000]}\n"
        questions_text += f"Question: {q['prompt']}\n"
        for c in q["choices"]:
            marker = " [CORRECT]" if c["id"] == q["correctId"] else ""
            questions_text += f"  {c['id']}: {c['text']}{marker}\n"

    user_msg = f"""Analyze each question below and map it to skills from this skill tree.

**SKILL TREE NODES:**
{skill_list}

**QUESTIONS:**
{questions_text}

**For each question, return:**
1. relatedSkills: array of skill IDs that this question tests
2. correctAnswer: {{ id, indicatesKnowledge: [skill IDs demonstrated by correct answer] }}
3. wrongAnswers: for each wrong choice {{ indicatesMisunderstanding: [skill IDs the student likely lacks], reasoning: why a student might pick this }}

**Return ONLY valid JSON in this exact format, nothing else:**
{{
  "questionId1": {{
    "relatedSkills": ["U1S1", "U1S5"],
    "correctAnswer": {{
      "id": "A",
      "indicatesKnowledge": ["U1S1", "U1S5"]
    }},
    "wrongAnswers": {{
      "B": {{
        "indicatesMisunderstanding": ["U1S5"],
        "reasoning": "Student likely confused X with Y"
      }},
      "C": {{
        "indicatesMisunderstanding": ["U1S1"],
        "reasoning": "Student does not understand..."
      }}
    }}
  }},
  ...
}}"""

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
        existing = kv_get(f"question_analysis_job:{course_id}")
        if isinstance(existing, dict) and existing.get("status") == "processing":
            send_json(self, {
                "jobId": course_id,
                "batchId": existing.get("batchId", ""),
                "status": "processing",
                "message": "Analysis already in progress",
            })
            return

        # Load skill tree
        saved_tree = kv_get(f"skill_tree:{course_id}")
        if not isinstance(saved_tree, dict) or not saved_tree.get("mermaid"):
            send_json(self, {"error": "No skill tree found. Generate the skill tree first."}, 400)
            return

        skill_nodes = _parse_skill_nodes(saved_tree["mermaid"])
        if not skill_nodes:
            send_json(self, {"error": "Could not parse skill nodes from skill tree."}, 400)
            return

        # Normalize questions
        normalized = [_normalize_question(q) for q in questions]
        normalized = [q for q in normalized if q["id"] and q["prompt"]]
        if not normalized:
            send_json(self, {"error": "No valid questions found after normalization."}, 400)
            return

        # Save raw questions to KV
        kv_set(f"course_questions:{course_id}", {
            "questions": normalized,
            "count": len(normalized),
            "savedAt": time.time(),
        })

        # Delete existing analysis (for regeneration)
        kv_delete(f"question_analysis:{course_id}")

        # Chunk questions and build batch requests
        chunk_count = math.ceil(len(normalized) / CHUNK_SIZE)
        batch_requests = []
        for i in range(chunk_count):
            chunk = normalized[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
            system_msg, user_msg = _build_chunk_prompt(skill_nodes, chunk)
            batch_requests.append({
                "custom_id": f"qa-{course_id}-chunk{i}",
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

            kv_set(f"question_analysis_job:{course_id}", {
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
