"""POST /api/article-cleanup — Batch-process all lessons in a course to remove
article content that is already covered in the video.

Receives { courseId }.
Runs async in a background thread:
  1. Fetches PowerPath tree to find all lessons with video + article URLs
  2. For each lesson: fetches video transcript + article content
  3. Sends both to Claude to remove redundant article content
  4. Stores cleaned articles and summaries in KV

Poll /api/article-cleanup-status?courseId=... for progress/results.
"""

import json
import os
import re
import time
import threading
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import API_BASE, api_headers, send_json, get_query_params, get_token, CLIENT_ID, CLIENT_SECRET
from api._kv import kv_get, kv_set

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-4-20250514"

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"

SERVICE_USER_ID = "8ea2b8e1-1b04-4cab-b608-9ab524c059c2"


# ── Tree fetching (mirrors edit-course-load.py) ─────────────────────

def _try_tree(url, headers):
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 401:
            headers = api_headers()
            resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data
    except Exception:
        pass
    return None


def _fetch_tree(course_id):
    headers = api_headers()
    ids_to_try = [course_id]
    cached_pp100 = kv_get(f"pp100_course_id:{course_id}")
    if cached_pp100 and cached_pp100 != course_id:
        ids_to_try.append(cached_pp100)

    for cid in ids_to_try:
        tree = _try_tree(f"{API_BASE}/powerpath/lessonPlans/tree/{cid}", headers)
        if tree:
            return tree
    for cid in ids_to_try:
        tree = _try_tree(f"{API_BASE}/powerpath/lessonPlans/{cid}/{SERVICE_USER_ID}", headers)
        if tree:
            return tree
    return None


# ── Extract video+article URLs per lesson from tree ─────────────────

def _parse_resource_meta(res_wrapper):
    res = res_wrapper.get("resource", res_wrapper) if isinstance(res_wrapper, dict) else res_wrapper
    if not isinstance(res, dict):
        return "", "", "", ""
    meta = res.get("metadata") or {}
    rurl = meta.get("url", "") or res.get("url", "") or meta.get("href", "") or res.get("href", "")
    rtype = (meta.get("type", "") or res.get("type", "")).lower()
    res_title = res.get("title", "") or ""
    res_id = res.get("id", "") or res.get("sourcedId", "") or ""
    return rurl, res_id, res_title, rtype


def _extract_lessons_with_content(tree):
    """Walk the tree and extract lessons that have both a video URL and article URL."""
    inner = tree.get("lessonPlan", tree) if isinstance(tree, dict) else tree
    if isinstance(inner, dict) and inner.get("lessonPlan"):
        inner = inner["lessonPlan"]

    unit_list = inner.get("subComponents", []) if isinstance(inner, dict) else (inner if isinstance(inner, list) else [])

    lessons = []
    for unit in unit_list:
        if not isinstance(unit, dict):
            continue
        unit_title = unit.get("title", "")

        for lesson in unit.get("subComponents", []):
            if not isinstance(lesson, dict):
                continue
            lesson_title = lesson.get("title", "")
            lesson_id = lesson.get("sourcedId") or lesson.get("id") or ""

            video_url = ""
            article_url = ""
            for rw in lesson.get("componentResources", []):
                rurl, _rid, _rtitle, rtype = _parse_resource_meta(rw)
                if rtype == "video" and rurl:
                    video_url = video_url or rurl
                elif rurl and "stimuli" in rurl.lower():
                    article_url = article_url or rurl

            if video_url and article_url:
                lessons.append({
                    "lessonId": lesson_id,
                    "lessonTitle": lesson_title,
                    "unitTitle": unit_title,
                    "videoUrl": video_url,
                    "articleUrl": article_url,
                })

    return lessons


# ── Transcript fetching (mirrors analyze-relevance.py) ──────────────

def _fetch_transcript_text(video_url):
    if not video_url:
        return ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        m = re.search(r'(?:[?&]v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})', video_url)
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


# ── Article fetching (mirrors analyze-relevance.py) ─────────────────

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


def _strip_html(html):
    if not html:
        return ""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _fetch_article_html(article_url):
    """Fetch article/stimulus HTML content from QTI."""
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
                    return resp.text.strip()
            except Exception:
                continue
    except Exception:
        pass
    return ""


# ── Claude cleanup call ─────────────────────────────────────────────

def _cleanup_article(transcript, article_html):
    """Send transcript + article to Claude and get cleaned article back."""
    article_text = _strip_html(article_html)
    if not transcript or not article_text:
        return None

    system_msg = (
        "You are an expert educational content editor. Your job is to remove "
        "redundant content from an article that is already covered in a video transcript.\n\n"
        "RULES:\n"
        "- Compare the video transcript and article content\n"
        "- Remove sentences and paragraphs from the article that cover the same "
        "information as the video transcript\n"
        "- KEEP content that adds depth, new examples, details, data, or perspectives "
        "not covered in the video\n"
        "- KEEP any images, tables, or formatted data that the video cannot convey\n"
        "- Preserve the article's HTML structure and formatting\n"
        "- Do NOT add any new content\n"
        "- Do NOT rewrite or paraphrase — only remove\n\n"
        "Return ONLY valid JSON with these fields:\n"
        '{ "cleanedArticle": "the article HTML with redundant parts removed", '
        '"removedSummary": "brief description of what was removed", '
        '"removedCount": number_of_paragraphs_or_sections_removed }'
    )

    user_msg = (
        f"VIDEO TRANSCRIPT:\n{transcript[:12000]}\n\n"
        f"ARTICLE CONTENT:\n{article_text[:12000]}\n\n"
        "Remove content from the article that is already covered in the video. "
        "Return ONLY the JSON response."
    )

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
                "max_tokens": 8000,
                "system": system_msg,
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=120,
        )

        if resp.status_code != 200:
            return None

        data = resp.json()
        ai_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                ai_text = block.get("text", "")
                break

        return _extract_json(ai_text)
    except Exception:
        return None


def _extract_json(text):
    """Extract JSON from AI response."""
    stripped = re.sub(r'```(?:json)?\s*', '', text).strip()
    stripped = re.sub(r'```\s*$', '', stripped).strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass
    # Balanced-brace extraction
    for i, ch in enumerate(text):
        if ch == '{':
            depth = 0
            in_str = False
            esc = False
            for j in range(i, len(text)):
                c = text[j]
                if esc:
                    esc = False
                    continue
                if c == '\\' and in_str:
                    esc = True
                    continue
                if c == '"' and not esc:
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i:j + 1])
                        except Exception:
                            pass
                        break
    return None


# ── Background processing ───────────────────────────────────────────

def _process_course(course_id):
    """Background thread: process all lessons in the course."""
    kv_key = f"article_cleanup:{course_id}"

    try:
        # Fetch tree
        tree = _fetch_tree(course_id)
        if not tree:
            kv_set(kv_key, {"status": "error", "error": "Could not fetch course tree"})
            return

        lessons = _extract_lessons_with_content(tree)
        if not lessons:
            kv_set(kv_key, {
                "status": "done",
                "courseId": course_id,
                "totalLessons": 0,
                "processedLessons": 0,
                "skippedLessons": 0,
                "completedAt": time.time(),
                "results": {},
                "message": "No lessons found with both a video and article.",
            })
            return

        total = len(lessons)
        processed = 0
        skipped = 0
        results = {}

        # Update progress
        kv_set(kv_key, {
            "status": "processing",
            "courseId": course_id,
            "totalLessons": total,
            "processedLessons": 0,
            "skippedLessons": 0,
            "startedAt": time.time(),
        })

        for lesson in lessons:
            lid = lesson["lessonId"] or lesson["lessonTitle"]

            # Fetch transcript
            transcript = _fetch_transcript_text(lesson["videoUrl"])
            if not transcript:
                skipped += 1
                processed += 1
                results[lid] = {
                    "lessonTitle": lesson["lessonTitle"],
                    "unitTitle": lesson["unitTitle"],
                    "skipped": True,
                    "reason": "No transcript available",
                }
                kv_set(kv_key, {
                    "status": "processing",
                    "courseId": course_id,
                    "totalLessons": total,
                    "processedLessons": processed,
                    "skippedLessons": skipped,
                    "startedAt": time.time(),
                })
                continue

            # Fetch article
            article_html = _fetch_article_html(lesson["articleUrl"])
            if not article_html:
                skipped += 1
                processed += 1
                results[lid] = {
                    "lessonTitle": lesson["lessonTitle"],
                    "unitTitle": lesson["unitTitle"],
                    "skipped": True,
                    "reason": "No article content available",
                }
                kv_set(kv_key, {
                    "status": "processing",
                    "courseId": course_id,
                    "totalLessons": total,
                    "processedLessons": processed,
                    "skippedLessons": skipped,
                    "startedAt": time.time(),
                })
                continue

            # Cleanup with Claude
            original_text = _strip_html(article_html)
            original_wc = len(original_text.split())

            result = _cleanup_article(transcript, article_html)
            if result and result.get("cleanedArticle"):
                cleaned_text = _strip_html(result["cleanedArticle"])
                cleaned_wc = len(cleaned_text.split())
                results[lid] = {
                    "lessonTitle": lesson["lessonTitle"],
                    "unitTitle": lesson["unitTitle"],
                    "originalWordCount": original_wc,
                    "cleanedWordCount": cleaned_wc,
                    "removedSummary": result.get("removedSummary", ""),
                    "removedCount": result.get("removedCount", 0),
                    "cleanedHtml": result["cleanedArticle"],
                }
            else:
                skipped += 1
                results[lid] = {
                    "lessonTitle": lesson["lessonTitle"],
                    "unitTitle": lesson["unitTitle"],
                    "skipped": True,
                    "reason": "AI cleanup failed",
                }

            processed += 1
            # Update progress in KV after each lesson
            kv_set(kv_key, {
                "status": "processing",
                "courseId": course_id,
                "totalLessons": total,
                "processedLessons": processed,
                "skippedLessons": skipped,
                "startedAt": time.time(),
            })

        # Done
        kv_set(kv_key, {
            "status": "done",
            "courseId": course_id,
            "totalLessons": total,
            "processedLessons": processed,
            "skippedLessons": skipped,
            "completedAt": time.time(),
            "results": results,
        })

    except Exception as e:
        print(f"[article-cleanup] Error: {e}")
        kv_set(kv_key, {"status": "error", "error": str(e)})


# ── Handler ─────────────────────────────────────────────────────────

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

        course_id = (body.get("courseId") or "").strip()
        if not course_id:
            send_json(self, {"error": "Missing courseId"}, 400)
            return

        if not ANTHROPIC_API_KEY:
            send_json(self, {"error": "ANTHROPIC_API_KEY not configured"}, 500)
            return

        # Set initial status
        kv_set(f"article_cleanup:{course_id}", {
            "status": "processing",
            "courseId": course_id,
            "totalLessons": 0,
            "processedLessons": 0,
            "startedAt": time.time(),
        })

        # Start background thread
        thread = threading.Thread(
            target=_process_course,
            args=(course_id,),
            daemon=True,
        )
        thread.start()

        send_json(self, {"status": "processing", "courseId": course_id})
