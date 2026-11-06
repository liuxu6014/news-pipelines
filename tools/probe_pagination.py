"""Probe verified second-page and out-of-range behavior for selected sources."""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "run_reports" / "pagination_probe.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            return {
                "url": url,
                "status": response.status,
                "content_type": response.headers.get("Content-Type", ""),
                "body": body,
            }
    except HTTPError as exc:
        return {
            "url": url,
            "status": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "body": exc.read(),
        }
    except URLError as exc:
        return {
            "url": url,
            "status": None,
            "content_type": "",
            "body": b"",
            "error": str(exc.reason),
        }


def probe_mistras_api():
    template = "https://www.mistrasgroup.com/api/NewsFeed/GetNewsFeed/?page={page}&pageSize=50"
    first = fetch(template.format(page=1))
    second = fetch(template.format(page=2))
    out_of_range = fetch(template.format(page=9999))
    first_payload = json.loads(first["body"]) if first["status"] == 200 else {}
    second_payload = json.loads(second["body"]) if second["status"] == 200 else {}
    first_urls = {post.get("Url") for post in first_payload.get("Posts", [])}
    second_urls = {post.get("Url") for post in second_payload.get("Posts", [])}
    return {
        "source": "Onstream Pipeline Inspection / MISTRAS",
        "pagination_type": "api_page",
        "first_request": _compact(first, first_payload.get("MetaData")),
        "second_request": _compact(second, second_payload.get("MetaData")),
        "out_of_range_request": _compact(out_of_range),
        "needs_pagination": int(first_payload.get("MetaData", {}).get("PageCount") or 0) > 1,
        "page2_new_items_count": len(second_urls - first_urls),
        "stop_condition": "page_num > MetaData.PageCount or empty Posts",
        "pagination_success": first["status"] == 200 and second["status"] == 200 and bool(second_urls - first_urls),
        "out_of_range_behavior": out_of_range["status"],
    }


def probe_ppsa_archive():
    first = fetch("https://www.ppsa-online.com/newsletter/2026-05")
    second = fetch("https://www.ppsa-online.com/newsletter/2026-02")
    out_of_range = fetch("https://www.ppsa-online.com/newsletter/1900-01")
    return {
        "source": "PPSA",
        "pagination_type": "archive_links",
        "first_request": _compact(first),
        "second_request": _compact(second),
        "out_of_range_request": _compact(out_of_range),
        "needs_pagination": True,
        "page2_new_items_count": None,
        "stop_condition": "archive links exhausted",
        "pagination_success": first["status"] == 200 and second["status"] == 200,
        "out_of_range_behavior": out_of_range["status"],
    }


def probe_autofg_listing():
    listing = fetch("http://www.autofg.com/news/")
    body = listing["body"].decode("utf-8", errors="replace")
    detail_urls = sorted(
        set(re.findall(r'https?://www\.autofg\.com/news/\d+/\d+\.html', body))
    )
    pagination_links = bool(re.search(r"(?:下一页|下页|page=|list-\d+-\d+\.html)", body, re.I))
    return {
        "source": "中国自动化网",
        "pagination_type": "none_observed",
        "first_request": _compact(listing),
        "second_request": None,
        "out_of_range_request": None,
        "needs_pagination": pagination_links,
        "discovered_detail_count": len(detail_urls),
        "example_detail_urls": detail_urls[:3],
        "stop_condition": "section links exhausted",
        "pagination_success": listing["status"] == 200 and bool(detail_urls),
        "out_of_range_behavior": "not_applicable",
    }


def _compact(response, metadata=None):
    result = {
        "url": response["url"],
        "status": response["status"],
        "content_type": response["content_type"],
        "body_bytes": len(response["body"]),
    }
    if response.get("error"):
        result["error"] = response["error"]
    if metadata:
        result["metadata"] = metadata
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Probe source pagination and out-of-range behavior.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    probes = [probe_mistras_api(), probe_ppsa_archive(), probe_autofg_listing()]
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "pass" if all(probe["pagination_success"] for probe in probes) else "partial",
        "probes": probes,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
