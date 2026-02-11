"""
Proxy for fetching article/stimuli content from QTI / PowerPath.
Articles are QTI Stimulus objects (client.stimuli.get(stimulusId)).

Keeps it simple: extract stimulus ID → fetch from QTI API → render to HTML.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import re
import requests
import json
import html as html_mod
import xml.etree.ElementTree as ET

from _helpers import get_token, API_BASE, CLIENT_ID, CLIENT_SECRET

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"

# Short timeouts — Vercel serverless functions have limited execution time
TOKEN_TIMEOUT = 8
FETCH_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
_cached_token = {"qti": None, "default": None}


def _get_qti_token() -> str:
    """Get Cognito token with QTI admin scope."""
    if _cached_token["qti"]:
        return _cached_token["qti"]
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
            timeout=TOKEN_TIMEOUT,
        )
        if resp.status_code == 200:
            _cached_token["qti"] = resp.json()["access_token"]
            return _cached_token["qti"]
    except Exception:
        pass
    # Fall back to default token
    tok = get_token()
    _cached_token["qti"] = tok
    return tok


# ---------------------------------------------------------------------------
# Stimulus ID extraction
# ---------------------------------------------------------------------------
def _extract_stimulus_id(url: str) -> str:
    """Extract stimulus ID from URL like .../stimuli/SOME-ID."""
    m = re.search(r'/stimuli/([^/?#]+)', url)
    return m.group(1).strip("/") if m else ""


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------
def _try_fetch(url: str, token: str):
    """Fetch a URL, return (response, content_type) or (None, None)."""
    try:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/html, application/xml, */*",
            },
            timeout=FETCH_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp, resp.headers.get("Content-Type", "")
        return None, str(resp.status_code)
    except Exception as e:
        return None, str(e)


def _response_to_html(resp, content_type: str) -> str:
    """Convert an API response to renderable HTML."""
    ct = content_type.lower()
    text = resp.text

    # JSON → extract article body
    if "json" in ct:
        try:
            data = resp.json()
            return _extract_article_html(data)
        except Exception:
            return ""

    # XML → parse QTI stimulus
    if "xml" in ct or text.lstrip().startswith("<?xml") or text.lstrip().startswith("<qti"):
        return _parse_qti_xml(text)

    # HTML or plain text → return as-is
    if text and len(text.strip()) > 0:
        return text

    return ""


# ---------------------------------------------------------------------------
# QTI XML → HTML
# ---------------------------------------------------------------------------
def _parse_qti_xml(xml_text: str) -> str:
    """Parse QTI 3.0 XML and extract the stimulus body as HTML."""
    if not xml_text or not xml_text.strip():
        return ""
    try:
        # Strip XML namespaces for easier parsing
        cleaned = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', '', xml_text, count=10)
        cleaned = re.sub(r'<(/?)(\w+):', r'<\1', cleaned)

        root = ET.fromstring(cleaned)

        # Find stimulus-body element
        stim_body = None
        for tag in ["qti-stimulus-body", ".//qti-stimulus-body",
                     "stimulus-body", ".//stimulus-body"]:
            stim_body = root.find(tag)
            if stim_body is not None:
                break

        # Use root if it's a stimulus element
        if stim_body is None and "stimulus" in root.tag.lower():
            stim_body = root

        if stim_body is None:
            return ""

        return _xml_to_html(stim_body)
    except Exception:
        # Regex fallback
        for pat in [r'<qti-stimulus-body[^>]*>(.*?)</qti-stimulus-body>',
                     r'<stimulus-body[^>]*>(.*?)</stimulus-body>']:
            m = re.search(pat, xml_text, re.DOTALL | re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return ""


def _xml_to_html(el) -> str:
    """Recursively convert XML element tree to HTML."""
    parts = []
    if el.text and el.text.strip():
        parts.append(el.text)

    HTML_TAGS = {"p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6",
                 "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                 "strong", "b", "em", "i", "u", "blockquote", "pre", "code",
                 "sup", "sub", "figure", "figcaption"}
    VOID_TAGS = {"br", "hr"}

    for child in el:
        tag = child.tag.lower()
        if "}" in tag:
            tag = tag.split("}")[-1]

        if tag in HTML_TAGS:
            inner = _xml_to_html(child)
            safe = _safe_attrs(child)
            parts.append(f"<{tag}{safe}>{inner}</{tag}>")
        elif tag in VOID_TAGS:
            parts.append(f"<{tag}>")
        elif tag == "img":
            src = _esc(child.get("src", ""))
            alt = _esc(child.get("alt", ""))
            parts.append(f'<img src="{src}" alt="{alt}" style="max-width:100%;border-radius:8px;margin:12px 0;">')
        elif tag == "a":
            href = _esc(child.get("href", ""))
            inner = _xml_to_html(child)
            parts.append(f'<a href="{href}" target="_blank" rel="noopener">{inner}</a>')
        else:
            # QTI wrapper tags or unknown → just recurse
            inner = _xml_to_html(child)
            if inner.strip():
                parts.append(inner)

        if child.tail and child.tail.strip():
            parts.append(child.tail)

    return "".join(parts)


def _safe_attrs(el) -> str:
    """Pass through safe HTML attributes."""
    safe = {"class", "id", "style", "width", "height", "colspan", "rowspan"}
    out = []
    for k, v in el.attrib.items():
        if k.lower() in safe:
            out.append(f' {_esc(k)}="{_esc(v)}"')
    return "".join(out)


# ---------------------------------------------------------------------------
# QTI JSON → HTML (for JSON responses)
# ---------------------------------------------------------------------------
def _esc(s) -> str:
    if not s:
        return ""
    return html_mod.escape(str(s))


def _render_node(node) -> str:
    """Convert QTI JSON node to HTML (mirrors quiz.html renderNode)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_render_node(i) for i in node)
    if not isinstance(node, dict):
        return str(node)

    parts = []
    for key, val in node.items():
        if key.startswith("_"):
            continue
        if key in ("strong", "b"):
            parts.append(f"<strong>{val if isinstance(val, str) else _render_node(val)}</strong>")
        elif key in ("em", "i"):
            parts.append(f"<em>{val if isinstance(val, str) else _render_node(val)}</em>")
        elif key == "p":
            for p in (val if isinstance(val, list) else [val]):
                if isinstance(p, str):
                    parts.append(f"<p>{p}</p>")
                elif isinstance(p, dict) and "_" in p:
                    parts.append(f"<p>{p['_']}</p>")
                else:
                    parts.append(f"<p>{_render_node(p)}</p>")
        elif key in ("h1", "h2", "h3", "h4"):
            parts.append(f"<{key}>{val if isinstance(val, str) else _render_node(val)}</{key}>")
        elif key == "img":
            a = val.get("_attributes", val) if isinstance(val, dict) else {}
            parts.append(f'<img src="{_esc(a.get("src",""))}" alt="{_esc(a.get("alt",""))}" style="max-width:100%;border-radius:8px;margin:12px 0;">')
        elif key in ("span", "div"):
            for d in (val if isinstance(val, list) else [val]):
                parts.append(d if isinstance(d, str) else _render_node(d))
        elif key in ("ul", "ol"):
            items = val if isinstance(val, list) else [val]
            parts.append(f"<{key}>{''.join(f'<li>{i if isinstance(i,str) else _render_node(i)}</li>' for i in items)}</{key}>")
        elif key == "li":
            for i in (val if isinstance(val, list) else [val]):
                parts.append(f"<li>{i if isinstance(i, str) else _render_node(i)}</li>")
        elif key == "a":
            if isinstance(val, dict):
                a = val.get("_attributes", val)
                t = val.get("_", val.get("span", ""))
                parts.append(f'<a href="{_esc(a.get("href",""))}" target="_blank">{t if isinstance(t,str) else _render_node(t)}</a>')
            else:
                parts.append(str(val))
        elif key == "br":
            parts.append("<br>")
        elif isinstance(val, (dict, list)):
            parts.append(_render_node(val))
        elif isinstance(val, str) and val:
            parts.append(val)
    return "".join(parts)


def _extract_article_html(data: dict) -> str:
    """Extract renderable HTML from a QTI/PowerPath JSON response."""
    if not isinstance(data, dict):
        return ""

    # 1. qti-assessment-stimulus → qti-stimulus-body
    stim = data.get("qti-assessment-stimulus")
    if isinstance(stim, dict):
        body = stim.get("qti-stimulus-body", {})
        r = _render_node(body)
        if r and r.strip():
            return r

    # 2. Nested content wrapper
    content = data.get("content")
    if isinstance(content, dict):
        s2 = content.get("qti-assessment-stimulus")
        if isinstance(s2, dict):
            r = _render_node(s2.get("qti-stimulus-body", {}))
            if r and r.strip():
                return r

    # 3. Direct qti-stimulus-body
    sb = data.get("qti-stimulus-body")
    if sb:
        r = _render_node(sb)
        if r and r.strip():
            return r

    # 4. Simple body/content/html/text fields
    for f in ("body", "content", "html", "text"):
        v = data.get(f)
        if isinstance(v, str) and len(v.strip()) > 10:
            return v
        if isinstance(v, dict):
            r = _render_node(v)
            if r and r.strip():
                return r

    # 5. Nested data wrapper
    inner = data.get("data")
    if isinstance(inner, dict):
        return _extract_article_html(inner)

    return ""


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        url = (query.get("url") or [None])[0]
        res_id = (query.get("id") or [None])[0]

        if not url and not res_id:
            self._json(400, {"error": "Missing 'url' or 'id' parameter"})
            return

        try:
            token = _get_qti_token()

            # Extract stimulus ID from URL
            stim_id = ""
            if url and "stimuli" in url.lower():
                stim_id = _extract_stimulus_id(url)
            if not stim_id and res_id:
                stim_id = res_id

            # ── Try QTI stimulus endpoints (fast, 2 attempts max) ──
            if stim_id:
                for endpoint in [
                    f"{QTI_BASE}/api/stimuli/{stim_id}",
                    f"{API_BASE}/api/v1/qti/stimuli/{stim_id}/",
                ]:
                    resp, ct = _try_fetch(endpoint, token)
                    if resp:
                        html_out = _response_to_html(resp, ct)
                        if html_out:
                            self._html(200, html_out)
                            return

            # ── Fallback: fetch the original URL directly ──
            if url:
                resp, ct = _try_fetch(url, token)
                if resp:
                    html_out = _response_to_html(resp, ct)
                    if html_out:
                        self._html(200, html_out)
                        return
                    self._html(200, "")
                    return

                # Try with default (non-QTI) token
                default_tok = get_token()
                resp, ct = _try_fetch(url, default_tok)
                if resp:
                    html_out = _response_to_html(resp, ct)
                    if html_out:
                        self._html(200, html_out)
                        return

                self._json(502, {"error": f"Could not fetch article from upstream"})
            else:
                self._json(404, {"error": "Stimulus not found", "id": stim_id})

        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, status, content):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content.encode() if isinstance(content, str) else content)
