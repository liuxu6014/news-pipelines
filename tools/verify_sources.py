"""Rigorously verify every flat spider: static contract + live source availability.

Part 1 (static, offline): metadata, valid URLs, SSRF allowlist, Scrapy 2.16 entry
    point (``async def start``, no dead ``start_requests``).
Part 2 (live, network): probe entry/section/start URLs with a browser UA and
    classify each source as reachable / blocked (anti-bot) / empty / unreachable.

Writes ``run_reports/source_verification.json`` and prints a readable summary.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from scrapy.spiderloader import SpiderLoader
from scrapy.utils.project import get_project_settings

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.runtime.spider_configs import discover_spider_configs

REPORT_JSON = ROOT / "run_reports" / "source_verification.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

ANTI_BOT_MARKERS = ("cloudflare", "incapsula", "just a moment", "captcha", "challenge-platform")
MIN_CONTENT_BYTES = 600


def _load_spider_class(name):
    loader = SpiderLoader.from_settings(get_project_settings())
    return loader.load(name)


def static_audit(name, cfg, cls):
    issues = []
    for attr in ("site_id", "site_name", "site_type", "language", "source_category"):
        if not getattr(cls, attr, None):
            issues.append(f"missing:{attr}")
    entry = cfg.get("entry_url") or ""
    if not entry:
        issues.append("missing:entry_url")
    for url in cfg.get("section_urls") or []:
        if not url.startswith(("http://", "https://")):
            issues.append(f"bad_section_url:{url}")
            break
    for url in cfg.get("start_urls") or []:
        if not url.startswith(("http://", "https://")):
            issues.append(f"bad_start_url:{url}")
            break
    if "start_requests" in cls.__dict__:
        issues.append("dead:start_requests")
    if "start" not in cls.__dict__:
        issues.append("missing:async_start")

    domains = list(getattr(cls, "allowed_domains", None) or [])
    custom = getattr(cls, "custom_settings", None) or {}
    allow = tuple(custom.get("SSRF_ALLOWED_HOSTS", []) or ())
    if domains and not allow:
        issues.append("missing:ssrf_allowlist")
    elif domains and allow:
        for d in domains:
            if d not in allow or f"*.{d}" not in allow:
                issues.append(f"ssrf_incomplete:{d}")
                break
    return issues


def _probe_url(url, timeout=12):
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "*/*"},
            timeout=timeout,
            verify=True,
            allow_redirects=True,
        )
        body = r.text[:1500].lower()
        ctype = r.headers.get("Content-Type", "")
        size = len(r.content)
        anti_bot = r.status_code in (401, 403, 429) or any(m in body for m in ANTI_BOT_MARKERS)
        return {
            "status": r.status_code,
            "content_type": ctype,
            "size": size,
            "anti_bot": bool(anti_bot),
            "empty": size < MIN_CONTENT_BYTES,
            "error": "",
        }
    except Exception as exc:
        return {
            "status": 0,
            "content_type": "",
            "size": 0,
            "anti_bot": False,
            "empty": True,
            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
        }


def _classify(probes):
    if not probes:
        return "unreachable", ""
    ok = [p for p in probes if p["status"] == 200 and not p["anti_bot"] and not p["empty"]]
    if ok:
        return "reachable", ok[0]["content_type"].split(";")[0]
    blocked = [p for p in probes if p["anti_bot"] or p["status"] in (401, 403, 429)]
    if blocked and not any(p["status"] == 200 for p in probes):
        return "blocked", str(blocked[0]["status"])
    if any(p["status"] == 200 for p in probes):
        return "empty", "200-small-body"
    first_err = next((p for p in probes if p["error"]), None)
    return "unreachable", (first_err or {}).get("error", "")[:60] or "no-200"


def main():
    configs = discover_spider_configs(include_example=False)
    rows = []
    static_issues_total = 0

    # Static audit + URL collection.
    probe_tasks = []
    for cfg in configs:
        name = cfg["name"]
        cls = _load_spider_class(name)
        issues = static_audit(name, cfg, cls)
        if issues:
            static_issues_total += len(issues)
        urls = []
        for candidate in [cfg.get("entry_url"), *(cfg.get("start_urls") or []), *(cfg.get("section_urls") or [])]:
            if candidate and candidate not in urls and candidate.startswith(("http://", "https://")):
                urls.append(candidate)
            if len(urls) >= 3:
                break
        rows.append(
            {
                "name": name,
                "site_name": cfg.get("site_name") or name,
                "category": getattr(cls, "source_category", "") or "",
                "site_type": cfg.get("site_type") or "",
                "entry_url": cfg.get("entry_url") or "",
                "issues": issues,
                "urls": urls,
            }
        )
        for u in urls:
            probe_tasks.append((name, u))

    # Live probe.
    results = {}
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = {pool.submit(_probe_url, u): (name, u) for name, u in probe_tasks}
        for fut in as_completed(futures):
            name, u = futures[fut]
            results.setdefault(name, []).append({"url": u, **fut.result()})

    for row in rows:
        probes = results.get(row["name"], [])
        verdict, detail = _classify(probes)
        row["verdict"] = verdict
        row["detail"] = detail
        row["probes"] = probes

    report = {
        "total": len(rows),
        "static_issues_total": static_issues_total,
        "verdicts": _tally(rows),
        "spiders": rows,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"TOTAL spiders: {len(rows)}")
    print(f"STATIC issues: {static_issues_total}")
    print("VERDICTS:")
    for verdict, count in sorted(_tally(rows).items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:12s} {count}")
    print()
    print("DETAIL (non-reachable):")
    for row in rows:
        if row["verdict"] != "reachable":
            print(f"  [{row['verdict']:11s}] {row['name']}  {row['detail']}  {row['site_name']}")
    print()
    print("STATIC issues detail:")
    for row in rows:
        if row["issues"]:
            print(f"  {row['name']}: {', '.join(row['issues'])}")
    print(f"\nreport -> {REPORT_JSON}")


def _tally(rows):
    tally = {}
    for row in rows:
        tally[row["verdict"]] = tally.get(row["verdict"], 0) + 1
    return tally


if __name__ == "__main__":
    main()
