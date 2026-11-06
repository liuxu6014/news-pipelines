"""Seed the flat per-site spiders into pipe-sight's ``data_sources`` catalog.

Writes one ``data_sources`` row per spider so users can start/stop each crawler
from the pipe-sight UI. Each row is keyed by the spider ``name`` (stored in
``config.spider_name``) and marked ``adapter='news_pipelines_spider'``. Re-runs
are idempotent and preserve an admin's existing ``is_enabled`` choice.

Usage::

    uv run python tools/seed_data_sources.py
    uv run python tools/seed_data_sources.py --dry-run
    uv run python tools/seed_data_sources.py --reactivate   # re-enable disabled sources
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.runtime.source_gate import SOURCE_ADAPTER, pg_connection_kwargs
from app.runtime.spider_configs import discover_spider_configs


def _first_http_url(entry):
    return entry.get("entry_url") or entry.get("url") or None


def _source_type(entry):
    site_id = (entry.get("site_id") or "").lower()
    url = (_first_http_url(entry) or "").lower()
    return "wechat" if "mp.weixin.qq.com" in site_id or "mp.weixin.qq.com" in url else "website"


def _source_name(entry):
    return (entry.get("site_name") or entry.get("title") or entry.get("name") or "未知来源")[:255]


def _source_config(entry):
    return {
        "spider_name": entry.get("name"),
        "site_id": entry.get("site_id") or "",
        "site_type": entry.get("site_type") or "",
        "language": entry.get("language") or "",
    }


def _fetch_row(connection, spider_name):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, is_enabled FROM data_sources "
            "WHERE adapter = %s AND config->>'spider_name' = %s ORDER BY id LIMIT 1",
            (SOURCE_ADAPTER, spider_name),
        )
        return cursor.fetchone()


def _upsert(connection, entry, reactivate=False):
    from psycopg2.extras import Json

    spider_name = entry.get("name")
    name = _source_name(entry)
    source_type = _source_type(entry)
    url = _first_http_url(entry)
    config = Json(_source_config(entry))
    existing = _fetch_row(connection, spider_name)
    if existing:
        source_id, is_enabled = existing
        if reactivate:
            is_enabled = True
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE data_sources SET name = %s, type = %s, url = %s, config = %s, "
                "is_enabled = %s WHERE id = %s",
                (name, source_type, url, config, is_enabled, source_id),
            )
        return "updated"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_sources (name, type, url, adapter, cron, timezone, next_run_at, "
            "config, model_id, is_enabled) "
            "VALUES (%s, %s, %s, %s, NULL, 'Asia/Shanghai', NULL, %s, NULL, true)",
            (name, source_type, url, SOURCE_ADAPTER, config),
        )
    return "created"


def main(argv=None):
    import psycopg2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print planned changes without writing")
    parser.add_argument(
        "--reactivate",
        action="store_true",
        help="re-enable previously disabled spider sources (default: preserve admin choice)",
    )
    args = parser.parse_args(argv)

    entries = discover_spider_configs(include_example=False)
    if not entries:
        print("未发现任何站点 spider，退出。", file=sys.stderr)
        return 1

    if args.dry_run:
        for entry in entries:
            print(f"  {entry.get('name')}  {_source_type(entry):8s}  {_source_name(entry)}")
        print(f"dry-run：共 {len(entries)} 个数据源待写入（--reactivate={args.reactivate}）")
        return 0

    created = updated = 0
    connection = psycopg2.connect(**pg_connection_kwargs())
    try:
        for entry in entries:
            action = _upsert(connection, entry, reactivate=args.reactivate)
            if action == "created":
                created += 1
            else:
                updated += 1
        connection.commit()
    finally:
        connection.close()

    print(f"数据源种子完成：total={len(entries)} created={created} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
