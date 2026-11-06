"""Helpers for item dedupe keys and content-change hashes."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

DEFAULT_DROP_QUERY_PARAMS = {
    "_",
    "from",
    "share",
    "spm",
    "timestamp",
}


def _is_tracking_param(key, extra_drop_params=None):
    key = str(key or "")
    drop_params = set(DEFAULT_DROP_QUERY_PARAMS)
    drop_params.update(extra_drop_params or ())
    return key in drop_params or key.startswith("utm_")


def canonicalize_url(url, base_url=None, drop_query_params=None):
    """Normalize a URL enough for dedupe without guessing site-specific semantics."""
    absolute = urljoin(base_url or "", str(url or "").strip())
    parts = urlsplit(absolute)
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(key, drop_query_params)
    ]
    query_pairs.sort()
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            urlencode(query_pairs, doseq=True),
            "",
        )
    )


def sha256_text(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def item_hashes(item):
    canonical_url = canonicalize_url(item.get("canonical_url") or item.get("url"))
    content = str(item.get("content") or item.get("content_md") or item.get("summary") or "")
    return {
        "canonical_url": canonical_url,
        "url_hash": sha256_text(canonical_url),
        "content_hash": sha256_text(content),
    }
