"""Per-spider enable/disable gate backed by pipe-sight ``data_sources``.

The ``pipesight`` platform (``D:\\A_CODEBASE\\pipe-sight``) owns the source
catalog: each flat per-site spider in this project corresponds to one
``data_sources`` row, keyed by the spider ``name`` in ``config.spider_name`` and
marked with ``adapter='news_pipelines_spider'``. Users toggle ``is_enabled`` in
the pipe-sight UI; this module reads that state so ``run_spider.py`` only runs
enabled spiders.

The gate is opt-in: it is disabled unless ``PIPESIGHT_SOURCE_GATE=1``, and any
failure to reach the database (or a missing spider row) falls back to running
the spider so a broken control plane never silently stops crawling. Set
``PIPESIGHT_SOURCE_GATE_ALLOW_UNKNOWN=0`` to require every spider to have an
explicit row before it may run.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from app.runtime.spider_configs import entry_name

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ADAPTER = "news_pipelines_spider"
_LOGGER = logging.getLogger("app.runtime.source_gate")

_DEFAULTS = {
    "PG_HOST": "127.0.0.1",
    "PG_PORT": "5432",
    "PG_DATABASE": "pipesight",
    "PG_USER": "postgres",
    "PG_PASSWORD": "",
    "PG_CONNECT_TIMEOUT": "10",
}


def _load_env():
    with contextlib.suppress(ImportError):
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def gate_enabled():
    """Whether ``run_spider.py`` should consult pipe-sight's source catalog."""
    _load_env()
    return _env_bool("PIPESIGHT_SOURCE_GATE", False)


def allow_unknown_sources():
    """Whether spiders without a ``data_sources`` row are allowed to run."""
    _load_env()
    return _env_bool("PIPESIGHT_SOURCE_GATE_ALLOW_UNKNOWN", True)


def pg_connection_kwargs():
    """PostgreSQL connection kwargs for the pipe-sight ``pipesight`` database."""
    _load_env()
    return {
        "host": os.getenv("PG_HOST", _DEFAULTS["PG_HOST"]),
        "port": int(os.getenv("PG_PORT", _DEFAULTS["PG_PORT"])),
        "dbname": os.getenv("PG_DATABASE", _DEFAULTS["PG_DATABASE"]),
        "user": os.getenv("PG_USER", _DEFAULTS["PG_USER"]),
        "password": os.getenv("PG_PASSWORD", _DEFAULTS["PG_PASSWORD"]),
        "connect_timeout": int(os.getenv("PG_CONNECT_TIMEOUT", _DEFAULTS["PG_CONNECT_TIMEOUT"])),
    }


def load_spider_enablement(connection_factory=None):
    """Return ``{spider_name: is_enabled}`` for every spider-backed source.

    Reads only rows marked ``adapter='news_pipelines_spider'``. Raises on any
    connection or query error; callers are expected to fall back to running all
    spiders. An empty result means "no rows seeded", not "everything disabled".
    """
    import psycopg2

    connect = connection_factory or psycopg2.connect
    connection = connect(**pg_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT config->>'spider_name' AS spider_name, is_enabled "
                "FROM data_sources WHERE adapter = %s",
                (SOURCE_ADAPTER,),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    result = {}
    for name, is_enabled in rows:
        name = (name or "").strip()
        if name:
            result[name] = bool(is_enabled)
    return result


def select_enabled(entries, logger=None, connection_factory=None):
    """Split ``entries`` into ``(enabled, disabled)`` per the source catalog.

    ``disabled`` is a list of ``(entry, reason)`` tuples for logging. When the
    gate is off or the database cannot be reached, every entry is enabled.
    """
    log = logger or _LOGGER
    if not gate_enabled():
        return list(entries), []
    try:
        enablement = load_spider_enablement(connection_factory=connection_factory)
    except Exception as exc:  # 控制面故障不得阻断采集
        log.warning("PIPESIGHT_SOURCE_GATE_FAILED error=%s; running all spiders", exc)
        return list(entries), []

    allow_unknown = allow_unknown_sources()
    enabled = []
    disabled = []
    for entry in entries:
        name = entry_name(entry)
        known = name in enablement
        if enablement.get(name, allow_unknown):
            enabled.append(entry)
        else:
            reason = "disabled_in_pipesight" if known else "not_in_pipesight"
            disabled.append((entry, reason))
    return enabled, disabled
