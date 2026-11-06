"""Discover stable feed, sitemap, API, and HTML detail endpoints for zero-yield sources."""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = PROJECT_ROOT / "run_reports" / "full_sources_20261022_user" / "audit_report.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "run_reports" / "source_endpoint_discovery.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
DISCOVERY_PATHS = (
    "/robots.txt",
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/wp-sitemap.xml",
    "/news-sitemap.xml",
    "/feed",
    "/feed.xml",
    "/rss.xml",
    "/atom.xml",
)
DETAIL_HINT_RE = re.compile(
    r"(?:news|article|press|story|insight|media|content|detail|xw|xinwen|dongtai|tzgg)/.+",
    re.I,
)


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read(1_500_000)
            return {
                "url": response.url,
                "status": response.status,
                "content_type": response.headers.get("Content-Type", ""),
                "body": body,
            }
    except HTTPError as exc:
        return {
            "url": url,
            "status": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "body": exc.read(200_000),
        }
    except URLError as exc:
        return {
            "url": url,
            "status": None,
            "content_type": "",
            "body": b"",
            "error": str(exc.reason),
        }


def origin_for(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def endpoint_candidates(site):
    origin = origin_for(site)
    if not origin:
        return []
    return [origin + path for path in DISCOVERY_PATHS]


def classify_endpoint(response):
    content_type = response["content_type"].lower()
    body = response["body"]
    text = body.decode("utf-8", errors="replace")
    locations = re.findall(r"<loc>\s*([^<]+)", text, re.I)
    feed_links = re.findall(r"<(?:link|guid)>\s*([^<]+)", text, re.I)
    html_links = [
        urljoin(response["url"], value.replace("&amp;", "&"))
        for value in re.findall(r"""href=["']([^"'#]+)["']""", text, re.I)
    ]
    detail_links = [
        url
        for url in dict.fromkeys(html_links)
        if DETAIL_HINT_RE.search(urlparse(url).path) and not urlparse(url).path.lower().endswith(
            (".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".png")
        )
    ]
    if "xml" in content_type or response["url"].endswith((".xml", "feed", "rss")):
        endpoint_type = "feed_or_sitemap"
        extracted_count = len(locations or feed_links)
        examples = (locations or feed_links)[:3]
    elif "html" in content_type:
        endpoint_type = "html"
        extracted_count = len(detail_links)
        examples = detail_links[:3]
    else:
        endpoint_type = "other"
        extracted_count = 0
        examples = []
    return {
        "url": response["url"],
        "status": response["status"],
        "content_type": response["content_type"],
        "body_bytes": len(body),
        "endpoint_type": endpoint_type,
        "extracted_count": extracted_count,
        "examples": examples,
        "error": response.get("error", ""),
    }


def discover_source(source):
    site = source.get("site") or ""
    homepage = fetch(site) if site else None
    endpoints = endpoint_candidates(site)
    if homepage:
        text = homepage["body"].decode("utf-8", errors="replace")
        endpoints.extend(
            urljoin(site, value.replace("&amp;", "&"))
            for value in re.findall(
                r"""<link[^>]+type=["']application/(?:rss|atom)\+xml["'][^>]+href=["']([^"']+)""",
                text,
                re.I,
            )
        )
    endpoints = list(dict.fromkeys(endpoints))
    results = [classify_endpoint(fetch(url)) for url in endpoints]
    if homepage:
        results.insert(0, classify_endpoint(homepage))
    ranked = sorted(
        results,
        key=lambda row: (
            row["status"] != 200,
            row["endpoint_type"] not in {"feed_or_sitemap", "html"},
            -row["extracted_count"],
        ),
    )
    useful = [row for row in ranked if row["status"] == 200 and row["extracted_count"]]
    strategy = "none"
    if useful:
        strategy = "feed_or_sitemap" if useful[0]["endpoint_type"] == "feed_or_sitemap" else "html"
    return {
        "spider": source.get("spider", ""),
        "name": source.get("name", ""),
        "site": site,
        "current_zero_category": source.get("category", ""),
        "recommended_strategy": strategy,
        "best_endpoint": useful[0] if useful else None,
        "probes": results,
    }


def select_sources(audit, groups, categories, limit):
    selected = []
    for spider in audit.get("spiders", []):
        if groups and spider["spider"] not in groups:
            continue
        for source in spider.get("zero_sources", []):
            if categories and source.get("category") not in categories:
                continue
            selected.append({**source, "spider": spider["spider"]})
    return selected[:limit] if limit else selected


def main(argv=None):
    parser = argparse.ArgumentParser(description="Discover source-specific news endpoints.")
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--group", action="append", dest="groups")
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)

    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    sources = select_sources(audit, args.groups, args.categories, args.limit)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(discover_source, source): source for source in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "name": source.get("name", ""),
                        "site": source.get("site", ""),
                        "recommended_strategy": "error",
                        "error": str(exc),
                        "probes": [],
                    }
                )
    results.sort(key=lambda row: (row.get("spider", ""), row.get("name", "")))
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "pass" if results and all(row["recommended_strategy"] != "none" for row in results) else "partial",
        "source_count": len(results),
        "strategy_counts": {
            strategy: sum(1 for row in results if row["recommended_strategy"] == strategy)
            for strategy in ("feed_or_sitemap", "html", "none", "error")
        },
        "sources": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "source_count": payload["source_count"],
                "strategy_counts": payload["strategy_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
