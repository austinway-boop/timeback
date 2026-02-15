"""POST /api/generate-activity

Uses Claude Opus to generate a self-contained HTML activity from a
description and optional uploaded images (base64). The generation runs
in a background thread (like frq-grade) and returns an activityId
immediately for polling via /api/generate-activity-status.

Body: {
    courseId: string,
    description: string,
    images: [{ data: "base64...", mediaType: "image/png" }]  (optional)
}
"""

import json
import os
import time
import uuid
import threading
from http.server import BaseHTTPRequestHandler

import requests

from api._kv import kv_set

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """You are an expert interactive educational activity designer. You create self-contained HTML activities that are visually polished, engaging, and educational.

REQUIREMENTS FOR EVERY ACTIVITY YOU CREATE:
1. Output ONLY a single, complete HTML file (<!DOCTYPE html> through </html>). No explanation, no markdown, JUST the HTML.
2. All CSS must be inline in a <style> tag in the <head>.
3. All JavaScript must be inline in a <script> tag before </body>.
4. The activity must be fully self-contained — no external dependencies, CDNs, or imports.
5. The activity MUST have a clear completion state. When the student completes it successfully, call:
   window.parent.postMessage({ type: 'activity-complete', score: 100 }, '*');
6. If the student gets it partially right, send a score between 0-100.
7. Include a visible "Check" or "Submit" button so the student knows when to check their work.
8. Include clear instructions at the top of the activity.
9. Use modern, clean design with good typography, spacing, and colors.
10. Make it responsive and work well in an iframe.
11. Include visual feedback for correct/incorrect states (green for correct, red for incorrect).
12. Include a "Reset" button to try again.
13. If an image is provided, use it as the base64 data URI directly in an <img> tag.

DESIGN GUIDELINES:
- Use a clean white background with subtle shadows and rounded corners
- Use a modern sans-serif font (system fonts: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif)
- Primary color: #45B5AA (teal), Error: #E53E3E, Success: #38A169
- Padding: 24px, Border radius: 12px
- Make interactive elements obvious with hover states and cursors
- Add smooth transitions and animations for state changes

ACTIVITY TYPES YOU CAN CREATE (but are not limited to):
- Drag and drop (drag items to correct positions on an image or into zones)
- Matching (connect items from two columns)
- Fill in the blank
- Multiple choice / multiple select
- Ordering / sequencing (put items in correct order)
- Labeling (label parts of a diagram)
- Sorting / categorization
- Interactive timelines
- Hotspot clicking (click correct regions on an image)
- Any other creative interactive format

For drag-and-drop activities with images:
- Use the provided image as background
- Create absolutely positioned drop zones over the relevant areas
- Make drag items snap into place when dropped correctly
- Use HTML5 drag and drop API (dragstart, dragover, drop events)
- Also support touch events for mobile compatibility"""


def _generate_async(activity_id, description, course_id, images):
    """Run generation in a background thread and store result in KV."""
    try:
        # Build the message content with optional images
        user_content = []
        for img in images:
            img_data = img.get("data", "")
            media_type = img.get("mediaType", "image/png")
            if img_data:
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_data,
                    },
                })

        user_content.append({
            "type": "text",
            "text": (
                f"Create an interactive educational activity based on this description:\n\n"
                f"{description}\n\n"
                f"Remember: Output ONLY the complete HTML file. No explanation, no markdown fences, "
                f"just the raw HTML starting with <!DOCTYPE html>."
            ),
        })

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
                    "budget_tokens": 10000,
                },
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}],
            },
            timeout=300,
        )

        if resp.status_code != 200:
            error_detail = resp.text[:500]
            print(f"[generate-activity] Anthropic error: {resp.status_code} {error_detail}")
            kv_set(f"custom_activity:{activity_id}", {
                "status": "error",
                "error": f"AI generation failed ({resp.status_code})",
            })
            return

        data = resp.json()
        html = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                html = block.get("text", "")
                break

        # Clean up any markdown fences that Claude might have added
        html = html.strip()
        if html.startswith("```html"):
            html = html[7:]
        elif html.startswith("```"):
            html = html[3:]
        if html.endswith("```"):
            html = html[:-3]
        html = html.strip()

        if not html or "<!DOCTYPE" not in html.upper()[:50]:
            print(f"[generate-activity] Invalid HTML output. Preview: {html[:300]}")
            kv_set(f"custom_activity:{activity_id}", {
                "status": "error",
                "error": "AI did not produce valid HTML",
            })
            return

        # Save completed activity to KV
        kv_set(f"custom_activity:{activity_id}", {
            "status": "complete",
            "activityId": activity_id,
            "description": description,
            "html": html,
            "courseId": course_id,
            "createdAt": time.time(),
        })

    except Exception as e:
        print(f"[generate-activity] Async error: {e}")
        kv_set(f"custom_activity:{activity_id}", {
            "status": "error",
            "error": str(e),
        })


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
            self._send({"error": "Invalid JSON"}, 400)
            return

        description = (body.get("description") or "").strip()
        course_id = (body.get("courseId") or "").strip()
        images = body.get("images") or []

        if not description:
            self._send({"error": "Missing description"}, 400)
            return

        if not ANTHROPIC_API_KEY:
            self._send({"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        # Generate activity ID and set initial "processing" status
        activity_id = f"act_{uuid.uuid4().hex[:12]}"
        kv_set(f"custom_activity:{activity_id}", {
            "status": "processing",
            "activityId": activity_id,
            "description": description,
            "courseId": course_id,
            "startedAt": time.time(),
        })

        # Start generation in background thread
        thread = threading.Thread(
            target=_generate_async,
            args=(activity_id, description, course_id, images),
            daemon=True,
        )
        thread.start()

        # Return immediately with the activity ID for polling
        self._send({
            "activityId": activity_id,
            "status": "processing",
        })

    def _send(self, data, status=200):
        body = json.dumps(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body.encode())
