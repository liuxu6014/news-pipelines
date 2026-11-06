"""Bounded live-extraction smoke test: does each spider actually yield items?

Runs every flat spider with tight limits (``CLOSESPIDER_ITEMCOUNT=3``,
``CLOSESPIDER_PAGECOUNT=20``, 15s download timeout) and records how many items
the spider scraped from the live site. Reachability alone is not enough — a
site can return 200 while the spider's XPath/section config extracts nothing.

Writes ``run_reports/source_extraction.json``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.runtime.spider_configs import discover_spider_configs

REPORT_JSON = ROOT / "run_reports" / "source_extraction.json"
OUT_DIR = ROOT / "run_reports" / "extract_smoke"
TIMEOUT_SECONDS = 60


def _count_items(name):
    out = OUT_DIR / f"{name}.jsonl"
    if not out.exists():
        return 0
    count = 0
    for line in out.open(encoding="utf-8"):
        if line.strip():
            count += 1
    return count


def _run_spider(name):
    out = OUT_DIR / f"{name}.jsonl"
    cmd = [
        sys.executable, "-m", "scrapy", "crawl", name,
        "-s", "CLOSESPIDER_ITEMCOUNT=3",
        "-s", "CLOSESPIDER_PAGECOUNT=20",
        "-s", "DOWNLOAD_TIMEOUT=15",
        "-s", "LOG_LEVEL=ERROR",
        "-o", str(out),
    ]
    row = {"name": name}
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        row["timeout"] = True
        row["items"] = _count_items(name)
        return row
    row["items"] = _count_items(name)
    if proc.returncode != 0:
        row["rc"] = proc.returncode
        row["stderr"] = (proc.stderr or "").strip()[-400:]
    return row


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    configs = discover_spider_configs(include_example=False)
    names = [cfg["name"] for cfg in configs]
    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_run_spider, n): n for n in names}
        for fut in as_completed(futures):
            row = fut.result()
            results[row["name"]] = row

    rows = [results[n] for n in names]
    empty = [r for r in rows if not r.get("items")]
    report = {
        "total": len(rows),
        "extracted": sum(1 for r in rows if r.get("items")),
        "empty": len(empty),
        "empty_names": [r["name"] for r in empty],
        "spiders": rows,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"TOTAL {report['total']}  extracted={report['extracted']}  empty={report['empty']}")
    print("EMPTY (yielded 0 items):")
    for r in empty:
        print("  ", r["name"])
    print(f"report -> {REPORT_JSON}")


if __name__ == "__main__":
    main()
