"""Shared helpers for configured spider filtering and validation."""

import fnmatch
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def project_root():
    return Path(__file__).resolve().parents[2]


def entry_spider(entry):
    return (entry or {}).get("spider") or (entry or {}).get("name")


def entry_name(entry):
    return (entry or {}).get("name")


def matches_token(value, token):
    if not value or not token:
        return False
    value = str(value)
    token = str(token)
    return value == token or token in value or fnmatch.fnmatchcase(value, token)


def matches_entry(entry, tokens):
    if not tokens:
        return True
    fields = (
        entry.get("spider", ""),
        entry.get("name", ""),
        entry.get("title", ""),
        entry.get("url", ""),
        entry.get("entry_url", ""),
        " ".join(entry.get("section_urls") or []),
        " ".join(entry.get("start_urls") or []),
        entry.get("file", ""),
        entry.get("folder", ""),
    )
    return any(matches_token(value, token) for token in tokens for value in fields)


def select_spiders(entries, spider_names=None, skip_names=None, limit=None, offset=0, available_spiders=None):
    selected = []
    skipped = []
    tokens = list(spider_names or [])
    skip_tokens = list(skip_names or [])
    available = set(available_spiders or []) if available_spiders is not None else None

    for entry in entries:
        if skip_tokens and matches_entry(entry, skip_tokens):
            skipped.append((entry, "excluded"))
            continue
        if tokens and not matches_entry(entry, tokens):
            skipped.append((entry, "not_selected"))
            continue
        spider_name = entry_spider(entry)
        if available is not None and spider_name not in available:
            skipped.append((entry, "not_available"))
            continue
        selected.append(entry)

    end = offset + limit if limit is not None else None
    return selected[offset:end], skipped


def load_available_spiders(root=None):
    result = subprocess.run(
        [sys.executable, "-m", "scrapy", "list"],
        cwd=Path(root or project_root()),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def validate_spider_config_entries(entries, root=None, available_spiders=None):
    root = Path(root or project_root())
    available = set(available_spiders or []) if available_spiders is not None else None
    seen_names = set()
    seen_spiders = set()
    errors = []
    for index, entry in enumerate(entries):
        name = str(entry_name(entry) or "").strip()
        if not name:
            errors.append(f"missing_name: index={index}")
        elif name in seen_names:
            errors.append(f"duplicate_name: {name}")
        seen_names.add(name)

        spider = str((entry or {}).get("spider") or "").strip()
        if not spider:
            errors.append(f"missing_spider: index={index}")
            continue
        if spider in seen_spiders:
            errors.append(f"duplicate_spider: {spider}")
        seen_spiders.add(spider)
        if available is not None and spider not in available:
            errors.append(f"not_available: {spider}")

        file_path = str(entry.get("file") or "").strip()
        if file_path and not (root / file_path).exists():
            errors.append(f"missing_file: {spider} {file_path}")

        url = str(entry.get("url") or entry.get("entry_url") or "").strip()
        if not url:
            section_urls = entry.get("section_urls") or []
            start_urls = entry.get("start_urls") or []
            for candidate in list(section_urls) + list(start_urls):
                candidate = str(candidate or "").strip()
                if candidate:
                    url = candidate
                    break
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                errors.append(f"invalid_url: {spider} {url}")
    return errors


def validate_spider_run_names(entries, run_names):
    config_names = {str(entry_name(entry) or "").strip() for entry in entries if str(entry_name(entry) or "").strip()}
    seen = set()
    errors = []
    for index, name in enumerate(run_names or []):
        name = str(name or "").strip()
        if not name:
            errors.append(f"empty_run_name: index={index}")
            continue
        if name in seen:
            errors.append(f"duplicate_run_name: {name}")
        seen.add(name)
        if name not in config_names:
            errors.append(f"run_name_not_configured: {name}")
    return errors


def filter_available_spider_configs(entries, available_spiders):
    available = set(available_spiders or [])
    return [entry for entry in entries if entry_spider(entry) in available]


def _iter_values(value):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        yield value.get("url")
        yield value.get("name")
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_values(item)
        return
    if value is not None:
        yield value


def _valid_http_url(url):
    return str(url or "").startswith(("http://", "https://"))


def _flatten_urls(value):
    urls = []
    for item in _iter_values(value):
        text = str(item or "").strip()
        if _valid_http_url(text):
            urls.append(text)
    return urls


def _first_http_url(values):
    for value in _iter_values(values):
        text = str(value or "").strip()
        if _valid_http_url(text):
            return text
    return ""


def discover_spider_configs(root=None, include_example=True):
    """Build ``SPIDER_CONFIGS`` entries by introspecting Scrapy's spider loader.

    Only flat per-site spiders living directly under ``app/spiders/``
    (``NNN_<host>.py``) are returned; legacy family packages in subdirectories
    are excluded. ``example`` is included only when ``include_example`` is true.
    """
    import inspect

    from scrapy.spiderloader import SpiderLoader
    from scrapy.utils.project import get_project_settings

    root = Path(root or project_root())
    rel_spiders_dir = Path("app") / "spiders"
    loader = SpiderLoader.from_settings(get_project_settings())
    entries = []
    for spider_name in sorted(loader.list()):
        if spider_name == "example" and not include_example:
            continue
        spider_cls = loader.load(spider_name)
        try:
            module_path = Path(inspect.getfile(spider_cls)).resolve()
            rel_path = module_path.relative_to(root)
        except (TypeError, ValueError):
            continue
        if rel_path.parent != rel_spiders_dir:
            continue
        section_urls = _flatten_urls(getattr(spider_cls, "section_urls", None))
        start_urls = _flatten_urls(getattr(spider_cls, "start_urls", None))
        entry_url = _first_http_url(
            [getattr(spider_cls, "entry_url", None), *section_urls, *start_urls]
        )
        title = (
            getattr(spider_cls, "source_title", None)
            or getattr(spider_cls, "site_name", None)
            or spider_name
        )
        entries.append(
            {
                "name": spider_name,
                "spider": spider_name,
                "title": title,
                "url": entry_url,
                "file": str(rel_path).replace("\\", "/"),
                "folder": "app/spiders",
                "entry_url": getattr(spider_cls, "entry_url", None) or "",
                "section_urls": section_urls,
                "start_urls": start_urls,
                "site_name": getattr(spider_cls, "site_name", None) or title,
                "site_type": getattr(spider_cls, "site_type", None) or "",
                "language": getattr(spider_cls, "language", None) or "",
                "jobdir": f"run_state/{spider_name}",
                "settings": {},
                "timeout_seconds": 0,
            }
        )
    return entries
