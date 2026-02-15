"""POST /api/frq-grade -- Grade a student's FRQ response using Claude 4.6 Opus Thinking.

Receives { promptId, studentResponse, subject, subjectName, category,
           questionType, questionTypeName, subSkill, rubric[], maxPoints, timerSeconds }
Retrieves the original prompt from KV, grades against the official AP rubric,
stores the result in KV, and returns a resultId for polling.
"""

import json
import os
import time
import uuid
import threading
from http.server import BaseHTTPRequestHandler

import requests

from api._kv import kv_get, kv_set, kv_list_push

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-opus-4-6"


def _build_rubric_text(rubric: list) -> str:
    """Format rubric rows into a readable text block."""
    lines = []
    for r in rubric:
        lines.append(f"  - {r.get('name', '')}: 0-{r.get('max', 0)} point(s)")
        lines.append(f"    Criteria: {r.get('desc', '')}")
    return "\n".join(lines)


def _build_grading_prompt(prompt_data: dict, body: dict) -> tuple:
    """Build system + user prompts for grading."""
    subject_name = body.get("subjectName", "")
    q_type_name = body.get("questionTypeName", "")
    sub_skill = body.get("subSkill", "full")
    rubric = body.get("rubric", [])
    max_points = body.get("maxPoints", 0)
    student_response = body.get("studentResponse", "")

    rubric_text = _build_rubric_text(rubric)

    sub_skill_instruction = ""
    if sub_skill != "full":
        target_row = next((r for r in rubric if r.get("id") == sub_skill), None)
        if target_row:
            sub_skill_instruction = (
                f"\n\nIMPORTANT: The student is practicing ONLY the '{target_row.get('name', sub_skill)}' sub-skill. "
                f"Grade ONLY this rubric row. For other rows, mark them as 0 with a note that they were not being practiced. "
                f"Provide detailed, focused feedback on this specific skill."
            )

    system_msg = (
        f"You are an expert AP {subject_name} exam reader/grader. "
        "You grade student free-response answers using the official College Board AP rubric "
        "with the same standards applied at the actual AP Reading.\n\n"
        "GRADING PRINCIPLES:\n"
        "- Each rubric point is earned independently\n"
        "- Grade based on the preponderance of evidence in the response\n"
        "- First-draft quality is acceptable; minor grammatical errors are not penalized unless they obscure meaning\n"
        "- A response may contain errors that do not detract from quality if the historical/scientific content is defensible\n"
        "- Be fair but rigorous — match the standards of actual AP grading\n\n"
        "FEEDBACK TONE (CRITICAL — follow exactly):\n"
        "- NEVER say 'Wrong', 'Incorrect', 'No', or any harsh evaluative language\n"
        "- For earned points: 'Strong work here — your [specific element] clearly demonstrates [criterion]'\n"
        "- For missed points: 'Your response touches on X, which shows understanding of... "
        "To earn this point, the AP rubric requires Y — try Z next time'\n"
        "- Acknowledge what the student attempted before explaining what's needed\n"
        "- Each rubric row gets 2-3 sentences of specific, actionable feedback\n"
        "- Overall tone: encouraging, specific, and constructive — like a helpful AP teacher\n\n"
        f"RUBRIC ({q_type_name}, {max_points} points total):\n{rubric_text}\n"
        f"{sub_skill_instruction}\n\n"
        "Return ONLY valid JSON in this exact format:\n"
        '{\n'
        '  "totalScore": <number>,\n'
        '  "maxScore": <number>,\n'
        '  "rubricRows": [\n'
        '    {\n'
        '      "id": "<rubric row id>",\n'
        '      "name": "<rubric row name>",\n'
        '      "earned": <points earned>,\n'
        '      "max": <max points for this row>,\n'
        '      "feedback": "<2-3 sentence feedback following the tone above>",\n'
        '      "excerpts": ["<relevant quote from student response>"]  // 0-2 excerpts\n'
        '    }\n'
        '  ],\n'
        '  "overallFeedback": "<2-3 paragraph overall assessment>",\n'
        '  "strengths": ["<specific strength 1>", "<strength 2>"],\n'
        '  "improvements": ["<specific improvement 1>", "<improvement 2>"]\n'
        '}'
    )

    # Build the full context
    user_parts = [f"Grade this {q_type_name} response for {subject_name}.\n"]

    # Include the original prompt
    if prompt_data.get("prompt"):
        user_parts.append(f"=== FRQ PROMPT ===\n{prompt_data['prompt']}\n")

    if prompt_data.get("instructions"):
        user_parts.append(f"=== INSTRUCTIONS ===\n{prompt_data['instructions']}\n")

    # Include documents/sources
    docs = prompt_data.get("documents", [])
    if docs:
        user_parts.append("=== DOCUMENTS/SOURCES ===")
        for i, doc in enumerate(docs):
            user_parts.append(f"Document {i + 1}: {doc.get('source', '')}")
            user_parts.append(doc.get("content", ""))
            user_parts.append("")

    if prompt_data.get("passage"):
        user_parts.append(f"=== PASSAGE ===\n{prompt_data['passage']}\n")

    if prompt_data.get("article"):
        user_parts.append(f"=== ARTICLE ===\n{prompt_data['article']}\n")

    if prompt_data.get("dataDescription"):
        user_parts.append(f"=== DATA ===\n{prompt_data['dataDescription']}\n")

    # Student response
    user_parts.append(f"=== STUDENT RESPONSE ===\n{student_response}\n")
    user_parts.append("Grade this response now. Return ONLY JSON.")

    user_msg = "\n".join(user_parts)

    return system_msg, user_msg


def _extract_json(text: str) -> dict | None:
    """Extract JSON from the AI response."""
    import re
    stripped = re.sub(r'```(?:json)?\s*', '', text).strip()
    stripped = re.sub(r'```\s*$', '', stripped).strip()

    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
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
                        try:
                            return json.loads(text[i:j + 1])
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
            i = j + 1 if depth == 0 else i + 1
        else:
            i += 1
    return None


def _grade_async(result_id: str, prompt_data: dict, body: dict):
    """Run grading in background and store result in KV."""
    try:
        system_msg, user_msg = _build_grading_prompt(prompt_data, body)

        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 16000,
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 16000,
                },
                "system": system_msg,
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=180,
        )

        if resp.status_code != 200:
            print(f"[frq-grade] Anthropic API error: {resp.status_code} {resp.text[:500]}")
            kv_set(f"frq_result:{result_id}", {
                "status": "error",
                "error": f"AI grading failed ({resp.status_code})",
            })
            return

        data = resp.json()
        ai_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                ai_text = block.get("text", "")
                break

        result = _extract_json(ai_text)
        if not result:
            print(f"[frq-grade] Failed to parse JSON. Preview: {ai_text[:500]}")
            kv_set(f"frq_result:{result_id}", {
                "status": "error",
                "error": "Failed to parse grading result",
            })
            return

        # Store complete result
        kv_set(f"frq_result:{result_id}", {
            "status": "complete",
            "result": result,
            "completedAt": time.time(),
        })

        # Save to history
        user_id = body.get("userId", "")
        if user_id:
            history_entry = {
                "resultId": result_id,
                "promptId": body.get("promptId", ""),
                "subject": body.get("subject", ""),
                "subjectName": body.get("subjectName", ""),
                "questionType": body.get("questionType", ""),
                "questionTypeName": body.get("questionTypeName", ""),
                "totalScore": result.get("totalScore", 0),
                "maxScore": result.get("maxScore", 0),
                "subSkill": body.get("subSkill", "full"),
                "date": time.time(),
            }
            kv_list_push(f"frq_history:{user_id}", history_entry)

    except Exception as e:
        print(f"[frq-grade] Async grading error: {e}")
        kv_set(f"frq_result:{result_id}", {
            "status": "error",
            "error": str(e),
        })


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

        prompt_id = body.get("promptId", "")
        student_response = body.get("studentResponse", "")

        if not prompt_id:
            _send_json(self, {"error": "Missing promptId"}, 400)
            return
        if not student_response or len(student_response.strip()) < 10:
            _send_json(self, {"error": "Response too short"}, 400)
            return
        if not ANTHROPIC_API_KEY:
            _send_json(self, {"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        # Retrieve original prompt
        prompt_data = kv_get(f"frq_prompt:{prompt_id}")
        if not isinstance(prompt_data, dict):
            _send_json(self, {"error": "Prompt not found"}, 404)
            return

        # Generate result ID and set initial status
        result_id = f"frq_r_{uuid.uuid4().hex[:12]}"
        kv_set(f"frq_result:{result_id}", {
            "status": "processing",
            "startedAt": time.time(),
        })

        # Start grading in background thread
        thread = threading.Thread(
            target=_grade_async,
            args=(result_id, prompt_data, body),
            daemon=True,
        )
        thread.start()

        _send_json(self, {
            "resultId": result_id,
            "status": "processing",
        })
