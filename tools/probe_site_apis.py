"""探测每个站点的真实数据源：JSON/XML 接口、内嵌 JSON 或服务端渲染 HTML。

输出一份 JSON 报告 + 可读摘要，供逐站改写 spider（有接口直接找接口）时参考。
用法：
    uv run python tools/probe_site_apis.py --category 政策机构 --limit 10
    uv run python tools/probe_site_apis.py --only pbc.gov.cn
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3

urllib3.disable_warnings()

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MANIFEST_JSON = ROOT / "docs" / "site_spiders_manifest.json"
REPORT_JSON = ROOT / "run_reports" / "site_api_probe.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 命中即视为“可能是接口”的 URL 关键词（按优先级）。
API_KEYWORDS = (
    "api", "json", "dataproxy", "jpage", "ajax", "getdata", "getjson",
    "listdata", "searchnews", "getnewlist", "querylist", "newslist",
    "infoservice", "webapp", "xgplayer", "portal/catalog",
)

# 命中即视为“可能是接口”的 URL 后缀。
API_SUFFIXES = (".json", ".do", ".action", ".jsp", ".xml", ".aspx", ".ashx")

# 命中即视为“接口数据”的路径段。
API_PATH_RE = re.compile(r"/(?:api|json|ajax|interface|rest|data|service|search)/", re.I)

# 内嵌 JSON：var xxx = {...} / window.xxx = {...}
EMBEDDED_JSON_RE = re.compile(
    r"(?:var\s+[A-Za-z_$][\w$]*\s*=|window\.[A-Za-z_$][\w$.]*\s*=|const\s+[A-Za-z_$][\w$]*\s*=)"
    r"\s*(\[[^\]]{10,}|\([^)]{10,}|\{[^{}]{10,})",
    re.S,
)

SITEMAP_PATHS = ("/sitemap.xml", "/sitemap.txt", "/sitemap_index.xml", "/sitemap1.xml")


def fetch(url, timeout=15):
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "*/*"},
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )
        return {
            "ok": True,
            "status": r.status_code,
            "final_url": r.url,
            "content_type": r.headers.get("Content-Type", ""),
            "charset": r.encoding or "",
            "length": len(r.content),
            "text": r.text,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def extract_api_candidates(text, base_url):
    """从 HTML/JS 里抽取疑似接口 URL（绝对 + 相对补全）。"""
    found = []
    for m in re.finditer(r"['\"]([^'\"]{3,300})['\"]", text):
        raw = m.group(1)
        if any(b in raw for b in (".js", ".css", ".png", ".jpg", ".gif", ".ico", ".svg", ".woff")):
            continue
        low = raw.lower()
        if not (any(k in low for k in API_KEYWORDS) or low.endswith(API_SUFFIXES) or API_PATH_RE.search(raw)):
            continue
        url = urljoin(base_url, raw) if not raw.startswith(("http://", "https://")) else raw
        if not url.startswith(("http://", "https://")):
            continue
        found.append(url)
    # 去重保持顺序
    seen = set()
    uniq = []
    for u in found:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def has_embedded_json(text):
    return bool(EMBEDDED_JSON_RE.search(text))


def probe_site(row):
    host = row["host"]
    entry = row["start_urls"][0]
    result = {"spider": row["spider"], "host": host, "entry_url": entry, "start_urls": row["start_urls"]}

    page = fetch(entry)
    if not page["ok"]:
        result["entry"] = {"ok": False, "error": page["error"]}
        return result

    text = page["text"]
    candidates = extract_api_candidates(text, page["final_url"])
    result["entry"] = {
        "ok": True,
        "status": page["status"],
        "content_type": page["content_type"],
        "charset": page["charset"],
        "length": page["length"],
        "embedded_json": has_embedded_json(text),
        "api_candidates": candidates[:15],
    }

    # sitemap 探测
    sitemap = []
    base = "https://" + host
    for path in SITEMAP_PATHS:
        try:
            r = requests.get(
                base + path,
                headers={"User-Agent": UA},
                timeout=8,
                verify=False,
                allow_redirects=True,
            )
            if r.status_code == 200 and ("xml" in r.headers.get("Content-Type", "").lower() or "<urlset" in r.text[:500] or "<sitemapindex" in r.text[:500]):
                sitemap.append({"url": r.url, "status": r.status_code, "length": len(r.content)})
        except Exception:
            pass
    result["sitemap"] = sitemap
    return result


def main():
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", default="", help="只探测指定分类，如：政策机构")
    parser.add_argument("--only", default="", help="只探测指定 host，逗号分隔")
    parser.add_argument("--limit", type=int, default=0, help="最多探测多少个站点")
    parser.add_argument("--workers", type=int, default=8, help="并发数")
    parser.add_argument("--timeout", type=int, default=15, help="单个请求超时秒数")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    rows = manifest
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]
    if args.only:
        hosts = {h.strip().lower() for h in args.only.split(",") if h.strip()}
        rows = [r for r in rows if r["host"] in hosts]
    if args.limit:
        rows = rows[: args.limit]

    print(f"探测 {len(rows)} 个站点（并发 {args.workers}）...")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe_site, row): row for row in rows}
        for done, fut in enumerate(as_completed(futures), 1):
            row = futures[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append({"spider": row["spider"], "host": row["host"], "entry": {"ok": False, "error": str(exc)}})
            if done % 10 == 0:
                print(f"  ... {done}/{len(rows)}", flush=True)

    results.sort(key=lambda r: r.get("host", ""))
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    # 可读摘要
    for r in results:
        entry = r.get("entry", {})
        if not entry.get("ok"):
            print(f"{r['host']:<30} ENTRY-FAIL {entry.get('error', '')}")
            continue
        flags = []
        if entry.get("embedded_json"):
            flags.append("embedded-json")
        if r.get("sitemap"):
            flags.append("sitemap")
        n_api = len(entry.get("api_candidates", []))
        if n_api:
            flags.append(f"api-candidates={n_api}")
        print(
            f"{r['host']:<30} HTTP{entry.get('status', 0):<3d} {entry.get('charset', ''):<8} {entry.get('content_type', '').split(';')[0]:<40} {','.join(flags)}"
        )
        for c in entry.get("api_candidates", [])[:4]:
            print(f"      | {c}")
    print(f"报告: {REPORT_JSON}")


if __name__ == "__main__":
    main()
