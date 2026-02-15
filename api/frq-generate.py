"""POST /api/frq-generate -- Generate an AP-style FRQ prompt.

Receives { subject, subjectName, category, units[], questionType, questionTypeName,
           subSkill, rubric[], maxPoints, timerMinutes }
Uses Claude 4.6 Opus Thinking to generate an authentic AP-style FRQ prompt
with documents/sources/reference material as appropriate.
"""

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler

import requests

from api._kv import kv_set

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-4-20250514"


def _build_generation_prompt(body: dict) -> tuple:
    """Build system + user prompts for FRQ generation."""
    subject_name = body.get("subjectName", "")
    category = body.get("category", "")
    units = body.get("units", [])
    q_type = body.get("questionType", "")
    q_type_name = body.get("questionTypeName", "")
    sub_skill = body.get("subSkill", "full")
    max_points = body.get("maxPoints", 0)
    rubric = body.get("rubric", [])

    units_text = ", ".join(units) if units else "All units"
    rubric_text = "\n".join(
        f"  - {r.get('name', '')}: {r.get('max', 0)} point(s) — {r.get('desc', '')}"
        for r in rubric
    )

    # Determine what kind of content to generate
    needs_documents = q_type in ("dbq",)
    needs_sources = q_type in ("synthesis",)
    needs_passage = q_type in ("rhetorical-analysis", "poetry-analysis", "prose-analysis")
    needs_scenario = q_type in ("concept-app", "quant-analysis", "scotus")
    needs_article = q_type in ("article-analysis",)
    needs_data = q_type in ("quant-analysis", "standard-frq", "investigative", "calculation-frq")
    is_science = category.startswith("science-")
    is_math = category.startswith("math-")
    is_code = category == "cs"

    system_msg = (
        "You are an expert AP exam question writer for College Board. "
        "You create authentic, exam-quality free-response questions that match "
        "the exact format, difficulty, and style of real AP exams.\n\n"
        "IMPORTANT RULES:\n"
        "- Generate questions that are appropriate for the specified units/topics\n"
        "- Match the exact format and structure of real AP exam FRQs\n"
        "- For history DBQs: generate exactly 7 authentic-sounding historical documents with source citations\n"
        "- For synthesis essays: generate 6-7 varied sources (articles, charts, letters, speeches)\n"
        "- For rhetorical/literary analysis: generate a passage that could appear on the actual exam\n"
        "- For science/math: include data, diagrams described in text, and multi-part structure\n"
        "- For AP Gov scenarios: create realistic political scenarios\n"
        "- All content should be historically/scientifically accurate\n"
        "- Questions should be challenging but fair for AP-level students\n\n"
        "Return ONLY valid JSON. No explanation outside the JSON."
    )

    # Build the specific generation instructions
    doc_instruction = ""
    if needs_documents:
        doc_instruction = (
            "\n\nFor the DBQ, generate exactly 7 documents. Each document must have:\n"
            "- 'source': The attribution (e.g., 'Letter from Thomas Jefferson to James Madison, 1787')\n"
            "- 'content': The actual document text (2-5 sentences, historically plausible)\n"
            "Include a mix of document types: letters, speeches, government reports, diary entries, "
            "newspaper articles, images described in text, and charts/data described in text."
        )
    elif needs_sources:
        doc_instruction = (
            "\n\nFor the Synthesis essay, generate 6 sources. Each source must have:\n"
            "- 'source': The attribution (e.g., 'Source A: Adapted from NY Times article, 2019')\n"
            "- 'content': The actual source text (3-6 sentences)\n"
            "Include a mix: news articles, academic papers, speeches, data/statistics, opinion pieces."
        )
    elif needs_passage:
        doc_instruction = (
            "\n\nGenerate or select a literary passage/poem that is appropriate for analysis. "
            "Include it in the 'passage' field. It should be a substantial excerpt (10-25 lines for poetry, "
            "2-4 paragraphs for prose) with rich literary/rhetorical devices to analyze."
        )
    elif needs_article:
        doc_instruction = (
            "\n\nGenerate a short research article summary (like a psychology study abstract, "
            "5-8 sentences) that students will analyze. Include research methods, variables, "
            "and findings. Include it in the 'article' field."
        )

    ref_instruction = ""
    if is_science or is_math:
        ref_instruction = (
            "\n\nInclude a 'referenceSheet' field with relevant formulas/constants "
            "the student would normally have access to on the AP exam for this subject."
        )

    sub_skill_instruction = ""
    if sub_skill != "full":
        sub_skill_instruction = (
            f"\n\nIMPORTANT: The student is practicing ONLY the '{sub_skill}' sub-skill. "
            "Generate the full prompt as normal (they need the context), but add a note in "
            "'instructions' explaining that the student should focus only on this specific skill."
        )

    json_format = (
        '{\n'
        '  "prompt": "The main FRQ prompt text (the question students must answer)",\n'
        '  "instructions": "Optional specific instructions or context for the student",\n'
        '  "documents": [{"source": "...", "content": "..."}],  // Only for DBQ/Synthesis\n'
        '  "passage": "...",  // Only for rhetorical/literary/poetry analysis\n'
        '  "article": "...",  // Only for psychology article analysis\n'
        '  "dataDescription": "...",  // For questions with charts/data (describe the data)\n'
        '  "referenceSheet": "..."  // Formulas/constants for science/math\n'
        '}'
    )

    user_msg = (
        f"Generate an AP-style Free Response Question for:\n\n"
        f"Subject: {subject_name}\n"
        f"Question Type: {q_type_name}\n"
        f"Max Points: {max_points}\n"
        f"Topics/Units to draw from: {units_text}\n\n"
        f"Official Rubric:\n{rubric_text}\n"
        f"{doc_instruction}{ref_instruction}{sub_skill_instruction}\n\n"
        f"Return ONLY this JSON format:\n{json_format}"
    )

    return system_msg, user_msg


def _send_json(handler, data, status=200):
    body = json.dumps(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body.encode())


def _extract_json(text: str) -> dict | None:
    """Extract JSON from the AI response, handling markdown fences."""
    import re
    stripped = re.sub(r'```(?:json)?\s*', '', text).strip()
    stripped = re.sub(r'```\s*$', '', stripped).strip()

    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Balanced-brace extraction
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

        if not body.get("subject"):
            _send_json(self, {"error": "Missing subject"}, 400)
            return
        if not body.get("questionType"):
            _send_json(self, {"error": "Missing questionType"}, 400)
            return
        if not ANTHROPIC_API_KEY:
            _send_json(self, {"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        system_msg, user_msg = _build_generation_prompt(body)

        try:
            resp = requests.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 10000,
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": 5000,
                    },
                    "system": system_msg,
                    "messages": [{"role": "user", "content": user_msg}],
                },
                timeout=120,
            )

            if resp.status_code != 200:
                error_detail = resp.text[:500]
                print(f"[frq-generate] Anthropic API error: {resp.status_code} {error_detail}")
                _send_json(self, {"error": f"AI generation failed ({resp.status_code})"}, 500)
                return

            data = resp.json()
            # Extract text from thinking response
            ai_text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    ai_text = block.get("text", "")
                    break

            result = _extract_json(ai_text)
            if not result:
                print(f"[frq-generate] Failed to parse JSON from AI. Preview: {ai_text[:500]}")
                _send_json(self, {"error": "Failed to parse AI response"}, 500)
                return

            # Generate a prompt ID and save to KV
            prompt_id = f"frq_{uuid.uuid4().hex[:12]}"
            kv_data = {
                "promptId": prompt_id,
                "subject": body.get("subject"),
                "subjectName": body.get("subjectName"),
                "category": body.get("category"),
                "questionType": body.get("questionType"),
                "questionTypeName": body.get("questionTypeName"),
                "subSkill": body.get("subSkill", "full"),
                "rubric": body.get("rubric", []),
                "maxPoints": body.get("maxPoints", 0),
                "timerMinutes": body.get("timerMinutes", 40),
                "prompt": result.get("prompt", ""),
                "instructions": result.get("instructions", ""),
                "documents": result.get("documents", []),
                "passage": result.get("passage", ""),
                "article": result.get("article", ""),
                "dataDescription": result.get("dataDescription", ""),
                "referenceSheet": result.get("referenceSheet", ""),
                "createdAt": time.time(),
            }
            kv_set(f"frq_prompt:{prompt_id}", kv_data)

            _send_json(self, {
                "promptId": prompt_id,
                "prompt": result.get("prompt", ""),
                "instructions": result.get("instructions", ""),
                "documents": result.get("documents", []),
                "passage": result.get("passage", ""),
                "article": result.get("article", ""),
                "dataDescription": result.get("dataDescription", ""),
                "referenceSheet": result.get("referenceSheet", ""),
                "timerMinutes": body.get("timerMinutes", 40),
            })

        except requests.exceptions.Timeout:
            _send_json(self, {"error": "AI generation timed out. Please try again."}, 504)
        except Exception as e:
            print(f"[frq-generate] Error: {e}")
            _send_json(self, {"error": f"Server error: {str(e)}"}, 500)
