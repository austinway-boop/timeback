"""
Proxy for fetching article/stimuli content from QTI / PowerPath.
These URLs require Cognito auth that the browser doesn't have.

Articles in the Timeback platform are QTI Stimulus objects fetched via:
  client.stimuli.get(stimulusId)  →  QTI 3.0 content

This proxy:
  1. Extracts the stimulus ID from the incoming URL
  2. Fetches from the correct QTI endpoint(s) with proper auth scope
  3. Handles both JSON and XML responses
  4. Renders QTI content to clean HTML for the lesson viewer
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import re
import requests
import json
import html as html_mod

from _helpers import get_token, API_BASE, CLIENT_ID, CLIENT_SECRET

COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
QTI_BASE = "https://qti.alpha-1edtech.ai"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _get_qti_token() -> str:
    """Get Cognito token with QTI admin scope (needed for stimuli endpoints)."""
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


# ---------------------------------------------------------------------------
# URL analysis & stimulus ID extraction
# ---------------------------------------------------------------------------
def _extract_stimulus_id(url: str) -> str:
    """Extract a stimulus ID from a URL like .../stimuli/SOME-ID or .../stimuli/SOME-ID/."""
    # Match /stimuli/{id} at the end of the path
    m = re.search(r'/stimuli/([^/?#]+)', url)
    if m:
        return m.group(1).strip("/")
    return ""


def _is_stimulus_url(url: str) -> bool:
    """Check if a URL targets a QTI stimulus endpoint."""
    lower = url.lower()
    return "stimuli" in lower


# ---------------------------------------------------------------------------
# Fetchers — try multiple QTI endpoints (mirrors qti-item.py approach)
# ---------------------------------------------------------------------------
def _fetch_json(url: str, headers: dict) -> tuple:
    """Fetch URL expecting JSON. Returns (data_dict, status) or (None, status)."""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                return resp.json(), 200
            # API might return XML even with JSON Accept header
            if "xml" in ct or resp.text.strip().startswith("<"):
                html_content = _parse_qti_xml(resp.text)
                if html_content:
                    return {"_rendered_html": html_content}, 200
            # Might be plain HTML
            if "html" in ct and resp.text.strip():
                return {"_rendered_html": resp.text}, 200
        return None, resp.status_code
    except Exception:
        return None, 0


def _fetch_stimulus_content(stim_id: str, token: str) -> str:
    """Fetch stimulus by ID from multiple QTI endpoints. Returns rendered HTML or empty string."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    # Endpoints to try, ordered by likelihood of success
    # (based on qti-item.py patterns and Timeback SDK config)
    urls = [
        f"{QTI_BASE}/api/stimuli/{stim_id}",
        f"{API_BASE}/api/v1/qti/stimuli/{stim_id}/",
        f"{API_BASE}/api/v1/qti/stimuli/{stim_id}",
        f"{QTI_BASE}/qti/v3/stimuli/{stim_id}",
        f"{API_BASE}/qti/v3/stimuli/{stim_id}",
    ]

    for url in urls:
        data, status = _fetch_json(url, headers)
        if data:
            # Check for pre-rendered HTML (from XML parsing)
            if "_rendered_html" in data:
                return data["_rendered_html"]
            # Extract article HTML from JSON
            article_html = _extract_article_html(data)
            if article_html:
                return article_html

    # Retry with default (non-QTI-scoped) token in case scope is wrong
    try:
        alt_token = get_token()
        if alt_token != token:
            alt_headers = {
                "Authorization": f"Bearer {alt_token}",
                "Accept": "application/json",
            }
            for url in urls:
                data, status = _fetch_json(url, alt_headers)
                if data:
                    if "_rendered_html" in data:
                        return data["_rendered_html"]
                    article_html = _extract_article_html(data)
                    if article_html:
                        return article_html
    except Exception:
        pass

    return ""


# ---------------------------------------------------------------------------
# QTI XML parsing → HTML
# ---------------------------------------------------------------------------
def _parse_qti_xml(xml_text: str) -> str:
    """Parse QTI 3.0 XML and extract the stimulus body as HTML."""
    try:
        import xml.etree.ElementTree as ET

        # QTI XML may have namespaces — strip them for easier parsing
        # Common QTI 3.0 namespace: http://www.imsglobal.org/xsd/imsqtiasi_v3p0
        cleaned = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', '', xml_text, count=10)
        # Also strip namespace prefixes from tags
        cleaned = re.sub(r'<(/?)(\w+):', r'<\1', cleaned)

        root = ET.fromstring(cleaned)

        # Find stimulus-body element (handles various tag names)
        stim_body = None
        for tag in [
            "qti-stimulus-body",
            "stimulus-body",
            "stimulusBody",
            ".//qti-stimulus-body",
            ".//stimulus-body",
        ]:
            stim_body = root.find(tag)
            if stim_body is not None:
                break

        # If no stimulus-body found, try the root if it's a stimulus
        if stim_body is None:
            tag_lower = root.tag.lower()
            if "stimulus" in tag_lower:
                # Use all child elements as the body
                stim_body = root

        if stim_body is None:
            return ""

        return _xml_element_to_html(stim_body)

    except Exception:
        # If XML parsing fails, try regex extraction as fallback
        return _regex_extract_stimulus(xml_text)


def _xml_element_to_html(element) -> str:
    """Recursively convert an XML element tree to HTML."""
    import xml.etree.ElementTree as ET

    parts = []

    # Add text before first child
    if element.text and element.text.strip():
        parts.append(element.text)

    for child in element:
        tag = child.tag.lower()
        # Remove namespace prefix if present
        if "}" in tag:
            tag = tag.split("}")[-1]

        # Map QTI tags to HTML
        if tag in ("p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6",
                    "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                    "strong", "b", "em", "i", "u", "br", "hr",
                    "blockquote", "pre", "code", "sup", "sub", "figure", "figcaption"):
            inner = _xml_element_to_html(child)
            attrs_str = _xml_attrs_to_html(child, tag)
            if tag == "br" or tag == "hr":
                parts.append(f"<{tag}{attrs_str}>")
            else:
                parts.append(f"<{tag}{attrs_str}>{inner}</{tag}>")
        elif tag == "img":
            src = child.get("src", "")
            alt = child.get("alt", "")
            parts.append(
                f'<img src="{_esc(src)}" alt="{_esc(alt)}" '
                f'style="max-width:100%;border-radius:8px;margin:12px 0;">'
            )
        elif tag == "a":
            href = child.get("href", "")
            inner = _xml_element_to_html(child)
            parts.append(
                f'<a href="{_esc(href)}" target="_blank" rel="noopener">{inner}</a>'
            )
        elif tag.startswith("qti-") or tag.startswith("stimulus"):
            # Recurse into QTI-specific elements, extracting their content
            parts.append(_xml_element_to_html(child))
        else:
            # Unknown tags — wrap in div or just include content
            inner = _xml_element_to_html(child)
            if inner.strip():
                parts.append(inner)

        # Add tail text (text after this child element)
        if child.tail and child.tail.strip():
            parts.append(child.tail)

    return "".join(parts)


def _xml_attrs_to_html(element, tag: str) -> str:
    """Convert relevant XML attributes to HTML attribute string."""
    attrs = element.attrib
    if not attrs:
        return ""
    # Only pass through safe HTML attributes
    safe_attrs = {"class", "id", "style", "width", "height", "colspan", "rowspan", "scope"}
    parts = []
    for k, v in attrs.items():
        if k.lower() in safe_attrs:
            parts.append(f' {_esc(k)}="{_esc(v)}"')
    return "".join(parts)


def _regex_extract_stimulus(xml_text: str) -> str:
    """Fallback: extract stimulus body content using regex when XML parsing fails."""
    # Try to find content between stimulus-body tags
    patterns = [
        r'<qti-stimulus-body[^>]*>(.*?)</qti-stimulus-body>',
        r'<stimulus-body[^>]*>(.*?)</stimulus-body>',
        r'<stimulusBody[^>]*>(.*?)</stimulusBody>',
    ]
    for pattern in patterns:
        m = re.search(pattern, xml_text, re.DOTALL | re.IGNORECASE)
        if m:
            body = m.group(1).strip()
            if body:
                return body
    return ""


# ---------------------------------------------------------------------------
# QTI JSON → HTML rendering (mirrors quiz.html renderNode)
# ---------------------------------------------------------------------------
def _esc(s) -> str:
    """HTML-escape a string."""
    if not s:
        return ""
    return html_mod.escape(str(s))


def _render_node(node) -> str:
    """Convert a QTI JSON node tree into HTML, similar to quiz.html renderNode."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_render_node(item) for item in node)
    if not isinstance(node, dict):
        return str(node)

    parts = []
    for key, val in node.items():
        if key.startswith("_"):
            continue

        if key in ("strong", "b"):
            inner = val if isinstance(val, str) else _render_node(val)
            parts.append(f"<strong>{inner}</strong>")
        elif key in ("em", "i"):
            inner = val if isinstance(val, str) else _render_node(val)
            parts.append(f"<em>{inner}</em>")
        elif key == "p":
            ps = val if isinstance(val, list) else [val]
            for p in ps:
                if isinstance(p, str):
                    parts.append(f"<p>{p}</p>")
                elif isinstance(p, dict) and "_" in p:
                    parts.append(f"<p>{p['_']}</p>")
                else:
                    parts.append(f"<p>{_render_node(p)}</p>")
        elif key in ("h1", "h2", "h3", "h4"):
            inner = val if isinstance(val, str) else _render_node(val)
            parts.append(f"<{key}>{inner}</{key}>")
        elif key == "img":
            attrs = val.get("_attributes", val) if isinstance(val, dict) else {}
            src = _esc(attrs.get("src", ""))
            alt = _esc(attrs.get("alt", ""))
            parts.append(
                f'<img src="{src}" alt="{alt}" style="max-width:100%;border-radius:8px;margin:12px 0;">'
            )
        elif key == "figure":
            figs = val if isinstance(val, list) else [val]
            for fig in figs:
                if not isinstance(fig, dict):
                    continue
                img_node = fig.get("img", {})
                img_attrs = (
                    img_node.get("_attributes", img_node)
                    if isinstance(img_node, dict)
                    else {}
                )
                src = _esc(img_attrs.get("src", ""))
                caption = fig.get("figcaption", "")
                cap_html = (
                    f'<figcaption style="font-size:0.88rem;color:#666;margin-top:8px;">{_esc(caption)}</figcaption>'
                    if caption
                    else ""
                )
                parts.append(
                    f'<figure style="text-align:center;margin:16px 0;">'
                    f'<img src="{src}" style="max-width:100%;border-radius:8px;">'
                    f"{cap_html}</figure>"
                )
        elif key == "span":
            inner = val if isinstance(val, str) else _render_node(val)
            parts.append(inner)
        elif key == "div":
            ds = val if isinstance(val, list) else [val]
            for d in ds:
                parts.append(_render_node(d))
        elif key in ("ul", "ol"):
            items = val if isinstance(val, list) else [val]
            li_html = "".join(
                f"<li>{item if isinstance(item, str) else _render_node(item)}</li>"
                for item in items
            )
            parts.append(f"<{key}>{li_html}</{key}>")
        elif key == "li":
            items = val if isinstance(val, list) else [val]
            for item in items:
                inner = item if isinstance(item, str) else _render_node(item)
                parts.append(f"<li>{inner}</li>")
        elif key == "a":
            if isinstance(val, dict):
                attrs = val.get("_attributes", val)
                href = _esc(attrs.get("href", ""))
                text = val.get("_", val.get("span", ""))
                if isinstance(text, dict):
                    text = _render_node(text)
                parts.append(
                    f'<a href="{href}" target="_blank" rel="noopener">{text}</a>'
                )
            else:
                parts.append(str(val))
        elif key == "br":
            parts.append("<br>")
        elif key == "blockquote":
            inner = val if isinstance(val, str) else _render_node(val)
            parts.append(f"<blockquote>{inner}</blockquote>")
        elif key == "table":
            parts.append(_render_node(val))
        elif key in ("thead", "tbody", "tr", "th", "td"):
            items = val if isinstance(val, list) else [val]
            for item in items:
                inner = item if isinstance(item, str) else _render_node(item)
                parts.append(f"<{key}>{inner}</{key}>")
        elif isinstance(val, (dict, list)):
            parts.append(_render_node(val))
        elif isinstance(val, str) and len(val) > 0:
            parts.append(val)

    return "".join(parts)


def _extract_article_html(data: dict) -> str:
    """Extract renderable HTML from a QTI or PowerPath JSON response."""

    # 1. QTI stimulus format: qti-assessment-stimulus → qti-stimulus-body
    stimulus = data.get("qti-assessment-stimulus")
    if stimulus and isinstance(stimulus, dict):
        stim_body = stimulus.get("qti-stimulus-body", {})
        rendered = _render_node(stim_body)
        if rendered and len(rendered.strip()) > 0:
            return rendered

    # 2. Nested content → qti-assessment-stimulus
    content = data.get("content")
    if isinstance(content, dict):
        stim2 = content.get("qti-assessment-stimulus")
        if stim2 and isinstance(stim2, dict):
            stim_body2 = stim2.get("qti-stimulus-body", {})
            rendered = _render_node(stim_body2)
            if rendered and len(rendered.strip()) > 0:
                return rendered

    # 3. Direct qti-stimulus-body at top level
    stim_body_direct = data.get("qti-stimulus-body")
    if stim_body_direct:
        rendered = _render_node(stim_body_direct)
        if rendered and len(rendered.strip()) > 0:
            return rendered

    # 4. PowerPath simple body/content/html/text fields
    for field in ("body", "content", "html", "text"):
        val = data.get(field)
        if isinstance(val, str) and len(val.strip()) > 10:
            return val
        if isinstance(val, dict):
            rendered = _render_node(val)
            if rendered and len(rendered.strip()) > 0:
                return rendered

    # 5. Check for nested data wrapper
    inner = data.get("data")
    if isinstance(inner, dict):
        return _extract_article_html(inner)

    # 6. Try rendering the entire response as QTI nodes (last resort)
    # Skip known non-content keys
    skip_keys = {"sourcedId", "id", "identifier", "title", "status", "dateLastModified",
                 "_attributes", "metadata", "type", "success", "error"}
    content_data = {k: v for k, v in data.items() if k not in skip_keys}
    if content_data:
        rendered = _render_node(content_data)
        if rendered and len(rendered.strip()) > 20:
            return rendered

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
        resource_id = (query.get("id") or [None])[0]

        if not url and not resource_id:
            self._json(400, {"error": "Missing 'url' or 'id' parameter"})
            return

        try:
            token = _get_qti_token()

            # ── Strategy 1: Stimulus ID-based fetch (most reliable) ──
            # Extract stimulus ID from URL or use provided ID
            stim_id = ""
            if url and _is_stimulus_url(url):
                stim_id = _extract_stimulus_id(url)
            if not stim_id and resource_id:
                stim_id = resource_id

            if stim_id:
                html_content = _fetch_stimulus_content(stim_id, token)
                if html_content:
                    self._html(200, html_content)
                    return

            # ── Strategy 2: Try resource ID as stimulus ID ──
            # The PowerPath resource ID might itself be a QTI stimulus identifier
            if resource_id and resource_id != stim_id:
                html_content = _fetch_stimulus_content(resource_id, token)
                if html_content:
                    self._html(200, html_content)
                    return

            # ── Strategy 3: Direct URL fetch ──
            if url:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/html, application/xml, */*",
                }
                resp = requests.get(url, headers=headers, timeout=30)

                # Retry with alternate token on auth failure
                if resp.status_code in (401, 403):
                    alt_token = get_token()
                    if alt_token != token:
                        headers["Authorization"] = f"Bearer {alt_token}"
                        resp = requests.get(url, headers=headers, timeout=30)

                if resp.status_code not in (200, 201):
                    self._json(resp.status_code, {
                        "error": f"Upstream returned {resp.status_code}",
                        "url": url,
                    })
                    return

                content_type = resp.headers.get("Content-Type", "")
                body_text = resp.text

                # Handle XML response
                if "xml" in content_type or body_text.strip().startswith("<?xml") or body_text.strip().startswith("<qti"):
                    html_content = _parse_qti_xml(body_text)
                    if html_content:
                        self._html(200, html_content)
                        return
                    self._html(200, body_text)
                    return

                # Handle JSON response
                if "json" in content_type:
                    data = resp.json()
                    article_html = _extract_article_html(data)
                    if article_html:
                        self._html(200, article_html)
                    else:
                        self._html(200, "")
                    return

                # Handle HTML or other text response
                if body_text and len(body_text.strip()) > 0:
                    self._html(200, body_text)
                else:
                    self._html(200, "")
            else:
                self._json(404, {"error": "Could not find article content"})

        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, status, html_content):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            html_content.encode() if isinstance(html_content, str) else html_content
        )
