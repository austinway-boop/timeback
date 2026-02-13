"""GET /api/video-transcript — Fetch and cache YouTube video transcripts.

GET  /api/video-transcript?url=YOUTUBE_URL
     → { "transcript": "full text...", "cached": false }

Uses youtube-transcript-api (no API key required).
Caches results in Upstash KV to avoid re-fetching.
"""

import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from api._kv import kv_get, kv_set

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    HAS_YT_API = True
except ImportError:
    HAS_YT_API = False


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None
    # youtube.com/watch?v=ID
    m = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
    if m:
        return m.group(1)
    # youtu.be/ID
    m = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
    if m:
        return m.group(1)
    # youtube.com/embed/ID
    m = re.search(r'youtube\.com/embed/([a-zA-Z0-9_-]{11})', url)
    if m:
        return m.group(1)
    return None


def _fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript text from YouTube."""
    if not HAS_YT_API:
        return None
    try:
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id)
        # Combine all snippet texts into a single string
        parts = []
        for snippet in transcript:
            text = snippet.text if hasattr(snippet, 'text') else str(snippet.get('text', ''))
            if text:
                parts.append(text)
        return " ".join(parts) if parts else None
    except Exception:
        return None


def _send_json(handler, data, status=200):
    body = json.dumps(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body.encode())


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        url = params.get("url", "")

        if not url:
            _send_json(self, {"error": "Missing url parameter"}, 400)
            return

        video_id = _extract_video_id(url)
        if not video_id:
            _send_json(self, {"error": "Could not extract YouTube video ID", "url": url}, 400)
            return

        # Check cache first
        cache_key = f"transcript_cache:{video_id}"
        cached = kv_get(cache_key)
        if cached and isinstance(cached, dict) and cached.get("transcript"):
            _send_json(self, {"transcript": cached["transcript"], "videoId": video_id, "cached": True})
            return

        # Fetch fresh transcript
        transcript = _fetch_transcript(video_id)
        if not transcript:
            _send_json(self, {
                "error": "Transcript unavailable",
                "videoId": video_id,
                "transcript": None,
            }, 200)  # 200 with null — not a server error
            return

        # Cache it
        kv_set(cache_key, {"transcript": transcript, "videoId": video_id})

        _send_json(self, {"transcript": transcript, "videoId": video_id, "cached": False})
