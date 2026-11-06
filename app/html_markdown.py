"""HTML fragment -> Markdown conversion used to fill ``content_md``.

Spiders fetch a detail page, locate the article body, and hand its HTML (plus the
page URL as ``base_url``) to :func:`html_to_markdown`. The result keeps the
original text, headings, links and inline images (``![alt](abs_url)``) so a
downstream reader renders the content close to the original page.

Images are also returned separately via :func:`html_images` for the ``images`` /
``image_url`` fields.

Only ``lxml`` (already a Scrapy dependency) is used; no extra package required.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lxml_html

# Tags dropped before conversion (navigation/boilerplate/scripts/embeds).
_STRIP_TAGS = {
    "script", "style", "noscript", "iframe", "form", "nav", "header", "footer",
    "aside", "button", "input", "select", "textarea", "svg", "canvas", "video",
    "audio", "object", "embed", "link", "meta", "title",
}

# Block-level elements produce their own paragraph/list/heading.
_BLOCK_TAGS = {
    "div", "p", "section", "article", "main", "aside", "figure", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre",
    "table", "tr", "hr", "address", "dl", "dt", "dd",
}

_HEADING_LEVEL = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_RE = re.compile(r"\n[ \t]*\n{2,}")

# A "data:" or "javascript:" image is useless in Markdown; keep only fetchable URLs.
_BAD_SRC_PREFIX = ("data:", "javascript:", "about:", "blob:")

# Common lazy-load / blank placeholders (lazy.gif, loading.gif, 1x1.gif, ...). Skip
# them so the real image attribute (data-src / original / srcset) wins instead.
_PLACEHOLDER_SRC_RE = re.compile(
    r"(?:lazy|loading|blank|pixel|spacer|1x1|nopic|placeholder|loading-pic)"
    r"(?:[-_0-9.]*\.(?:gif|png|jpe?g|webp|svg))?$",
    re.I,
)


def _clean_text(value):
    return _WS_RE.sub(" ", value or "")


def _abs(url, base_url):
    if not url:
        return ""
    url = url.strip()
    if not url or url.startswith(_BAD_SRC_PREFIX) or url.startswith("#"):
        return ""
    return urljoin(base_url or "", url)


def _img_srcs(node):
    """Return the candidate absolute image URLs for an <img>, best first."""
    srcs = []
    for attr in ("src", "original", "data-src", "data-original", "data-url", "data-lazy-src"):
        value = node.get(attr)
        if value and not _PLACEHOLDER_SRC_RE.search(value.split("?")[0].split("#")[0]):
            srcs.append(value.strip())
    # data-srcset: take the largest candidate for high-DPI rendering.
    srcset = node.get("data-srcset") or node.get("srcset") or ""
    if srcset:
        best = ""
        best_width = -1
        for candidate in srcset.split(","):
            part = candidate.strip().split()
            url = part[0] if part else ""
            if not url:
                continue
            width = 0
            if len(part) > 1:
                try:
                    width = int(re.sub(r"\D", "", part[1]) or 0)
                except ValueError:
                    width = 0
            if width >= best_width:
                best, best_width = url, width
        if best:
            srcs.append(best.strip())
    return srcs


class _Converter:
    def __init__(self, base_url):
        self.base_url = base_url or ""
        self.images = []
        self._seen_images = set()

    def _record_image(self, url):
        url = _abs(url, self.base_url)
        if url and url not in self._seen_images:
            self._seen_images.add(url)
            self.images.append(url)
        return url

    def _inline(self, el):
        """Render an element's inline content (text, links, images, emphasis)."""
        parts = []
        if el.text:
            parts.append(_clean_text(el.text))
        for child in el:
            parts.append(self._render_inline_node(child))
            if child.tail:
                parts.append(_clean_text(child.tail))
        return "".join(parts)

    def _render_inline_node(self, el):
        tag = el.tag
        if tag in _STRIP_TAGS:
            return ""
        if tag == "br":
            return "\n"
        if tag == "img":
            for src in _img_srcs(el):
                url = self._record_image(src)
                if url:
                    return f"![{_clean_text(el.get('alt') or '')}]({url})"
            return ""
        if tag == "a":
            text = self._inline(el)
            href = _abs(el.get("href") or "", self.base_url)
            if href and text:
                return f"[{text}]({href})"
            return text
        if tag in ("b", "strong"):
            return f"**{self._inline(el)}**"
        if tag in ("i", "em"):
            return f"*{self._inline(el)}*"
        if tag in ("code", "kbd", "samp"):
            return f"`{self._inline(el)}`"
        if tag in ("del", "s", "strike"):
            return f"~~{self._inline(el)}~~"
        # sub/sup and unknown inline tags: keep their text only.
        return self._inline(el)

    def render(self, el):
        """Render an element (block semantics) to Markdown."""
        tag = el.tag
        if tag in _STRIP_TAGS:
            return ""
        if tag in _HEADING_LEVEL:
            text = self._inline(el).strip()
            return f"{'#' * _HEADING_LEVEL[tag]} {text}" if text else ""
        if tag == "img":
            for src in _img_srcs(el):
                url = self._record_image(src)
                if url:
                    return f"![{_clean_text(el.get('alt') or '')}]({url})"
            return ""
        if tag == "br":
            return ""
        if tag == "hr":
            return "---"
        if tag == "blockquote":
            inner = self._render_block_children(el)
            return "\n".join(f"> {line}" for line in inner.splitlines()) if inner else ""
        if tag == "pre":
            return "```\n" + (el.text_content() or "").rstrip("\n") + "\n```"
        if tag == "ul":
            return self._render_list(el, ordered=False)
        if tag == "ol":
            return self._render_list(el, ordered=True)
        if tag == "table":
            return self._render_table(el)
        if tag == "li":
            return self._inline(el).strip()
        if tag in ("dt", "dd"):
            return self._inline(el).strip()
        # Default block: paragraphs / div / section / figure etc.
        return self._render_block_children(el)

    def _render_block_children(self, el):
        """Render a container: inline text plus nested blocks separated by blank lines."""
        blocks = []
        inline = []

        def flush_inline():
            text = "".join(inline).strip()
            if text:
                blocks.append(text)
            inline.clear()

        if el.text:
            inline.append(_clean_text(el.text))
        for child in el:
            if child.tag in _BLOCK_TAGS and child.tag != "br":
                flush_inline()
                rendered = self.render(child)
                if rendered.strip():
                    blocks.append(rendered)
            else:
                inline.append(self._render_inline_node(child))
            if child.tail:
                inline.append(_clean_text(child.tail))
        flush_inline()
        return "\n\n".join(block.strip() for block in blocks if block.strip())

    def _render_list(self, el, ordered):
        items = []
        for child in el.iterchildren("li"):
            rendered = self.render(child).strip()
            items.append(rendered)
        if not items:
            return ""
        if ordered:
            return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
        return "\n".join(f"- {item}" for item in items)

    def _render_table(self, el):
        rows = []
        for tr in el.iter("tr"):
            cells = []
            for cell in tr.iter("th", "td"):
                cells.append(" ".join(cell.itertext()).strip())
            if cells:
                rows.append(cells)
        if not rows:
            return self._render_block_children(el)
        col_count = max(len(row) for row in rows)
        for row in rows:
            row.extend([""] * (col_count - len(row)))
        header = rows[0]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in range(col_count)) + " |",
        ]
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


def _root_elements(html_fragment):
    """Parse a fragment (or document) into a list of top-level elements."""
    if not html_fragment:
        return []
    # lxml.html parses fragments by wrapping them in a <div>; documents keep <html>.
    doc = lxml_html.fromstring(html_fragment)
    if doc.tag in ("html", "body"):
        if doc.tag == "html":
            body = next(iter(doc.iter("body")), None)
            if body is not None:
                return body
        return list(doc)
    return [doc]


def html_to_markdown(html_fragment, base_url=""):
    """Convert an HTML fragment to clean Markdown (text + headings + links + images)."""
    if not html_fragment:
        return ""
    converter = _Converter(base_url)
    roots = _root_elements(html_fragment)
    blocks = []
    for root in roots:
        # Strip boilerplate everywhere before rendering.
        etree.strip_elements(root, *_STRIP_TAGS, with_tail=False)
        rendered = converter.render(root).strip()
        if rendered:
            blocks.append(rendered)
    markdown = "\n\n".join(blocks)
    return _BLANK_RE.sub("\n\n", markdown).strip()


def html_images(html_fragment, base_url=""):
    """Return the absolute image URLs of an HTML fragment, in document order."""
    if not html_fragment:
        return []
    converter = _Converter(base_url)
    for root in _root_elements(html_fragment):
        for img in root.iter("img"):
            for src in _img_srcs(img):
                converter._record_image(src)
    return converter.images


def html_plain_text(html_fragment):
    """Plain-text fallback for the ``content`` field (no Markdown markup)."""
    if not html_fragment:
        return ""
    doc = lxml_html.fromstring(html_fragment)
    etree.strip_elements(doc, *_STRIP_TAGS, with_tail=False)
    text = " ".join(doc.itertext())
    return _WS_RE.sub(" ", text).strip()
