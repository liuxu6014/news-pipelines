"""Item processing and optional MySQL / PostgreSQL persistence."""

import contextlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from app.item_deduplication import canonicalize_url, item_hashes
from app.runtime.spider_quality import (
    content_preview,
    crawled_at_now,
)
from app.runtime.spider_quality import (
    normalize_publish_time as normalize_contract_publish_time,
)

DEFAULT_MYSQL_HOST = "127.0.0.1"
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_DATABASE = "crawler"
DEFAULT_MYSQL_USER = "root"
DEFAULT_MYSQL_TABLE = "rss_news"
DEFAULT_MYSQL_CHARSET = "utf8mb4"
DEFAULT_MYSQL_BATCH_SIZE = 100

DEFAULT_PG_HOST = "127.0.0.1"
DEFAULT_PG_PORT = 5432
DEFAULT_PG_DATABASE = "pipesight"
DEFAULT_PG_USER = "postgres"
DEFAULT_PG_TABLE = "news_articles"
DEFAULT_PG_BATCH_SIZE = 100

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MYSQL_DEAD_LETTER_DIR = PROJECT_ROOT / "run_reports" / "mysql_dead_letters"
DEFAULT_PG_DEAD_LETTER_DIR = PROJECT_ROOT / "run_reports" / "pg_dead_letters"


def _inc_stat(stats, key, count=1):
    if stats and hasattr(stats, "inc_value"):
        stats.inc_value(key, count=count)


def _text(value):
    return "" if value is None else str(value).strip()


def normalize_publish_time(value):
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]


class ScrapyTemplatePipeline:
    """Normalize common fields before export or persistence."""

    TEXT_FIELDS = (
        "title",
        "url",
        "canonical_url",
        "content",
        "content_md",
        "content_preview",
        "summary",
        "raw_publish_time",
        "author",
        "source",
        "source_site",
        "source_category",
        "publish_time",
    )

    def __init__(self, stats=None, drop_missing_url=False):
        self.stats = stats
        self.drop_missing_url = drop_missing_url

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            stats=getattr(crawler, "stats", None),
            drop_missing_url=settings.getbool("DROP_ITEM_WITHOUT_URL", False),
        )

    def open_spider(self, spider=None):
        if spider and getattr(spider, "logger", None):
            spider.logger.info("Pipeline opened: %s", self.__class__.__name__)

    def process_item(self, item, spider=None):
        adapter = ItemAdapter(item)
        for field in self.TEXT_FIELDS:
            value = adapter.get(field)
            if isinstance(value, str):
                self._set(adapter, field, value.strip())

        url = adapter.get("url") or adapter.get("canonical_url")
        if not url and self.drop_missing_url:
            _inc_stat(self.stats, "app/item_dropped/missing_url")
            raise DropItem("missing_url")

        if url:
            if not adapter.get("canonical_url"):
                self._set(adapter, "canonical_url", canonicalize_url(url))
            if not adapter.get("source_site"):
                self._set(
                    adapter,
                    "source_site",
                    adapter.get("site_name") or adapter.get("org") or adapter.get("site"),
                )
            if not adapter.get("source_category"):
                self._set(adapter, "source_category", adapter.get("category"))
            if adapter.get("publish_time"):
                raw_publish_time = adapter.get("raw_publish_time") or adapter.get("publish_time")
                self._set(adapter, "raw_publish_time", raw_publish_time)
                normalized_publish_time = normalize_contract_publish_time(
                    adapter.get("publish_time")
                )
                if not normalized_publish_time:
                    normalized_publish_time = normalize_contract_publish_time(
                        raw_publish_time
                    )
                self._set(adapter, "publish_time", normalized_publish_time)
            if not adapter.get("content_preview"):
                self._set(adapter, "content_preview", content_preview(adapter.get("content")))
            if not adapter.get("crawled_at"):
                self._set(adapter, "crawled_at", crawled_at_now())
            hashes = item_hashes(adapter.asdict())
            for key, value in hashes.items():
                self._set(adapter, key, value)
        return item

    def close_spider(self, spider=None):
        if spider and getattr(spider, "logger", None):
            spider.logger.info("Pipeline closed: %s", self.__class__.__name__)

    @staticmethod
    def _set(adapter, key, value):
        # Scrapy Items require declared fields; dict items accept new fields.
        with contextlib.suppress(KeyError):
            adapter[key] = value


NEWS_COLUMNS = (
    "title",
    "url",
    "canonical_url",
    "url_hash",
    "content_hash",
    "content",
    "content_md",
    "summary",
    "publish_time",
    "author",
    "source",
    "source_site",
    "source_category",
    "domain",
    "image_url",
    "raw_item",
)


class _BaseItemPipeline:
    """Shared row-building, batching, upsert and dead-letter machinery.

    Concrete subclasses only provide the SQL dialect and connection factory:
    :class:`MySQLItemPipeline` and :class:`NewsArticlesPipeline`. Both write the
    same ``NEWS_COLUMNS`` and dedupe on ``url_hash``.
    """

    COLUMNS = NEWS_COLUMNS
    LABEL = "sql"
    STAT_PREFIX = "app/sql"
    TRANSIENT_CLASS_NAMES = frozenset({"operationalerror", "interfaceerror", "internalerror"})
    TRANSIENT_MARKERS = ()
    DEFAULT_DEAD_LETTER_DIR = PROJECT_ROOT / "run_reports" / "sql_dead_letters"

    def __init__(
        self,
        enabled=False,
        host="127.0.0.1",
        port=5432,
        database="",
        user="",
        password="",
        table="",
        connect_timeout=10,
        batch_size=100,
        fail_on_error=True,
        dead_letter_dir=None,
        dead_letter_include_rows=False,
        max_failed_batches=20,
        retry_times=0,
        retry_backoff_seconds=1.0,
        transient_error_types=None,
        connection_factory=None,
        stats=None,
    ):
        self.enabled = enabled
        self.host = host
        self.port = int(port)
        self.database = database
        self.user = user
        self.password = password
        self.table = table
        self.connect_timeout = int(connect_timeout)
        self.batch_size = max(1, int(batch_size or 1))
        self.fail_on_error = fail_on_error
        self.dead_letter_dir = Path(dead_letter_dir) if dead_letter_dir else self.DEFAULT_DEAD_LETTER_DIR
        self.dead_letter_include_rows = bool(dead_letter_include_rows)
        self.max_failed_batches = max(0, int(max_failed_batches or 0))
        self.retry_times = max(0, int(retry_times or 0))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds or 0))
        self.transient_error_types = tuple(transient_error_types or ())
        self.connection_factory = connection_factory or self._create_connection
        self.stats = stats
        self.connection = None
        self.errors = []
        self.failed_batches = []
        self.pending_rows = []
        self.write_attempted = 0
        self.write_succeeded = 0

    # -- row building (database-agnostic) ---------------------------------

    @classmethod
    def to_row(cls, item):
        data = ItemAdapter(item).asdict()
        hashes = item_hashes(data)
        canonical_url = hashes["canonical_url"]
        url = _text(data.get("url") or canonical_url)
        content = _text(data.get("content"))
        domain = _text(data.get("domain")) or cls._domain_from_url(canonical_url or url)
        normalized = {
            "title": _text(data.get("title")),
            "url": url,
            "canonical_url": canonical_url,
            "url_hash": hashes["url_hash"],
            "content_hash": hashes["content_hash"],
            "content": content,
            "content_md": _text(data.get("content_md")),
            "summary": _text(data.get("summary")),
            "publish_time": normalize_publish_time(data.get("publish_time") or data.get("published_at")),
            "author": _text(data.get("author")),
            "source": _text(data.get("source")),
            "source_site": _text(data.get("source_site") or data.get("site_name")),
            "source_category": _text(data.get("source_category") or data.get("category")),
            "domain": domain,
            "image_url": _text(data.get("image_url")),
            "raw_item": json.dumps(data, ensure_ascii=False, default=str),
        }
        if not normalized["canonical_url"]:
            raise DropItem("missing_canonical_url")
        return normalized

    @staticmethod
    def _domain_from_url(url):
        parsed = urlparse(url)
        return (parsed.hostname or "").lower().removeprefix("www.")

    # -- connection lifecycle ----------------------------------------------

    def _open_connection(self):
        return self.connection_factory(**self._connection_kwargs())

    def _reconnect(self):
        old_connection = self.connection
        if old_connection and hasattr(old_connection, "close"):
            with contextlib.suppress(Exception):
                old_connection.close()
        self.connection = self._open_connection()

    def open_spider(self, spider=None):
        if not self.enabled:
            self._log(spider, "info", "%s pipeline disabled", self.LABEL.upper())
            return
        try:
            self.connection = self._open_connection()
            self._log(
                spider,
                "info",
                "%s pipeline enabled: host=%s database=%s table=%s",
                self.LABEL.upper(),
                self.host,
                self.database,
                self.table,
            )
        except Exception as exc:
            self._record_error(exc, spider, "open")
            if self.fail_on_error:
                raise

    def close_spider(self, spider=None):
        if not self.connection:
            return
        try:
            self.flush(spider)
        finally:
            self._log(
                spider,
                "info",
                "%s_SUMMARY attempted=%s succeeded=%s failed=%s dead_letters=%s",
                self.LABEL.upper(),
                self.write_attempted,
                self.write_succeeded,
                len(self.errors),
                len(self.failed_batches),
            )
            self.connection.close()
        if self.errors and self.fail_on_error:
            raise RuntimeError(f"{self.LABEL.upper()} write failed for {len(self.errors)} operation(s)")

    # -- ingest / flush ------------------------------------------------------

    def process_item(self, item, spider=None):
        if not self.connection:
            return item
        self.process_row(self.to_row(item), spider)
        return item

    def process_row(self, row, spider=None):
        self.write_attempted += 1
        _inc_stat(self.stats, f"{self.STAT_PREFIX}/write_attempted")
        self.pending_rows.append(row)
        if len(self.pending_rows) >= self.batch_size:
            self.flush(spider)

    def flush(self, spider=None):
        if not self.connection or not self.pending_rows:
            return
        rows = list(self.pending_rows)
        try:
            self._execute_many(self.build_insert_sql(self.table), rows)
        except Exception as exc:
            _inc_stat(self.stats, f"{self.STAT_PREFIX}/write_failed", count=len(rows))
            first_row = rows[0] if rows else {}
            self._record_error(exc, spider, first_row.get("canonical_url") or first_row.get("url"))
            self._store_failed_batch(spider, rows, exc)
            self.pending_rows = []
            if self.fail_on_error:
                raise
        else:
            self.pending_rows = []
            self.write_succeeded += len(rows)
            _inc_stat(self.stats, f"{self.STAT_PREFIX}/write_succeeded", count=len(rows))

    def _execute(self, sql, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
        self.connection.commit()

    def _execute_many(self, sql, rows):
        attempts = self.retry_times + 1
        for attempt in range(attempts):
            try:
                with self.connection.cursor() as cursor:
                    if len(rows) == 1:
                        cursor.execute(sql, rows[0])
                    else:
                        cursor.executemany(sql, rows)
                self.connection.commit()
                return
            except Exception as exc:
                if attempt >= attempts - 1 or not self._is_transient_error(exc):
                    raise
                if self.connection and hasattr(self.connection, "rollback"):
                    self.connection.rollback()
                _inc_stat(self.stats, f"{self.STAT_PREFIX}/retry")
                if self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds)
                self._reconnect()

    def _is_transient_error(self, exc):
        if self.transient_error_types and isinstance(exc, self.transient_error_types):
            return True
        class_name = exc.__class__.__name__.lower()
        if class_name in self.TRANSIENT_CLASS_NAMES:
            return True
        message = str(exc).lower()
        return any(marker in message for marker in self.TRANSIENT_MARKERS)

    # -- errors / dead-letter -------------------------------------------------

    def _record_error(self, exc, spider, key):
        self.errors.append(exc)
        if self.connection and hasattr(self.connection, "rollback"):
            self.connection.rollback()
        self._log(spider, "error", "%s pipeline error: key=%s error=%s", self.LABEL.upper(), key, exc)

    def _store_failed_batch(self, spider, rows, exc):
        batch = {
            "spider": getattr(spider, "name", ""),
            "table": self.table,
            "row_count": len(rows),
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "row_keys": [self._dead_letter_row_key(row) for row in rows],
        }
        if self.dead_letter_include_rows:
            batch["rows"] = rows
        if self.max_failed_batches:
            self.failed_batches.append(batch)
            if len(self.failed_batches) > self.max_failed_batches:
                del self.failed_batches[: len(self.failed_batches) - self.max_failed_batches]
        try:
            self._append_dead_letter(batch)
        except Exception as dead_letter_exc:
            self._log(
                spider,
                "error",
                "%s dead-letter write failed: path=%s error=%s",
                self.LABEL.upper(),
                self._dead_letter_file(),
                dead_letter_exc,
            )

    def _dead_letter_file(self):
        return self.dead_letter_dir / f"{self.table}.jsonl"

    @staticmethod
    def _dead_letter_row_key(row):
        return {
            "canonical_url": row.get("canonical_url") or row.get("url") or "",
            "url_hash": row.get("url_hash") or "",
            "content_hash": row.get("content_hash") or "",
        }

    def _append_dead_letter(self, batch):
        path = self._dead_letter_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(batch, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _log(spider, level, message, *args):
        logger = getattr(spider, "logger", None)
        if logger and hasattr(logger, level):
            getattr(logger, level)(message, *args)


class MySQLItemPipeline(_BaseItemPipeline):
    """Upsert normalized items into MySQL with ``ON DUPLICATE KEY UPDATE``."""

    LABEL = "mysql"
    STAT_PREFIX = "app/mysql"
    DEFAULT_DEAD_LETTER_DIR = DEFAULT_MYSQL_DEAD_LETTER_DIR
    TRANSIENT_MARKERS = (
        "server has gone away",
        "lost connection",
        "connection reset",
        "deadlock",
        "lock wait timeout",
        "try restarting transaction",
    )

    def __init__(
        self,
        enabled=False,
        host=DEFAULT_MYSQL_HOST,
        port=DEFAULT_MYSQL_PORT,
        database=DEFAULT_MYSQL_DATABASE,
        user=DEFAULT_MYSQL_USER,
        password="",
        table=DEFAULT_MYSQL_TABLE,
        charset=DEFAULT_MYSQL_CHARSET,
        connect_timeout=10,
        batch_size=DEFAULT_MYSQL_BATCH_SIZE,
        fail_on_error=True,
        dead_letter_dir=None,
        dead_letter_include_rows=False,
        max_failed_batches=20,
        retry_times=0,
        retry_backoff_seconds=1.0,
        transient_error_types=None,
        connection_factory=None,
        stats=None,
    ):
        super().__init__(
            enabled=enabled,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            table=table,
            connect_timeout=connect_timeout,
            batch_size=batch_size,
            fail_on_error=fail_on_error,
            dead_letter_dir=dead_letter_dir,
            dead_letter_include_rows=dead_letter_include_rows,
            max_failed_batches=max_failed_batches,
            retry_times=retry_times,
            retry_backoff_seconds=retry_backoff_seconds,
            transient_error_types=transient_error_types,
            connection_factory=connection_factory,
            stats=stats,
        )
        self.charset = charset

    @classmethod
    def from_settings(cls, settings, stats=None):
        return cls(
            enabled=settings.getbool("MYSQL_ENABLED", False),
            host=settings.get("MYSQL_HOST", DEFAULT_MYSQL_HOST),
            port=settings.getint("MYSQL_PORT", DEFAULT_MYSQL_PORT),
            database=settings.get("MYSQL_DATABASE", DEFAULT_MYSQL_DATABASE),
            user=settings.get("MYSQL_USER", DEFAULT_MYSQL_USER),
            password=settings.get("MYSQL_PASSWORD", ""),
            table=settings.get("MYSQL_TABLE", DEFAULT_MYSQL_TABLE),
            charset=settings.get("MYSQL_CHARSET", DEFAULT_MYSQL_CHARSET),
            connect_timeout=settings.getint("MYSQL_CONNECT_TIMEOUT", 10),
            batch_size=settings.getint("MYSQL_BATCH_SIZE", DEFAULT_MYSQL_BATCH_SIZE),
            fail_on_error=settings.getbool("MYSQL_FAIL_ON_ERROR", True),
            dead_letter_dir=settings.get("MYSQL_DEAD_LETTER_DIR"),
            dead_letter_include_rows=settings.getbool("MYSQL_DEAD_LETTER_INCLUDE_ROWS", False),
            max_failed_batches=settings.getint("MYSQL_MAX_FAILED_BATCHES", 20),
            retry_times=settings.getint("MYSQL_RETRY_TIMES", 0),
            retry_backoff_seconds=settings.getfloat("MYSQL_RETRY_BACKOFF_SECONDS", 1.0),
            stats=stats,
        )

    @classmethod
    def from_crawler(cls, crawler):
        return cls.from_settings(crawler.settings, stats=getattr(crawler, "stats", None))

    @classmethod
    def _quote_identifier(cls, value):
        text = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+", text):
            raise ValueError(f"Invalid MySQL identifier: {value!r}")
        return f"`{text}`"

    @classmethod
    def build_insert_sql(cls, table):
        quoted_table = cls._quote_identifier(table)
        columns = ", ".join(cls._quote_identifier(column) for column in cls.COLUMNS)
        placeholders = ", ".join(f"%({column})s" for column in cls.COLUMNS)
        updates = ", ".join(
            f"{cls._quote_identifier(column)}=VALUES({cls._quote_identifier(column)})"
            for column in cls.COLUMNS
            if column != "url_hash"
        )
        return (
            f"INSERT INTO {quoted_table} ({columns}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}, "
            "`last_seen_at`=CURRENT_TIMESTAMP, `updated_at`=CURRENT_TIMESTAMP"
        )

    def _create_connection(self, **kwargs):
        import pymysql

        return pymysql.connect(**kwargs)

    def _connection_kwargs(self):
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password": self.password,
            "charset": self.charset,
            "connect_timeout": self.connect_timeout,
            "autocommit": False,
        }


class NewsArticlesPipeline(_BaseItemPipeline):
    """Upsert Kafka news messages into the ``news_articles`` PostgreSQL table.

    The target schema is the external ``pipesight`` database (not the MySQL
    ``rss_news`` table): rows key on the unique index ``md5(url)`` and must
    reference a valid ``data_sources.id`` via ``source_id``.
    """

    COLUMNS = (
        "source_id",
        "title",
        "url",
        "author",
        "published_at",
        "content",
        "content_zh",
        "category_id",
        "is_pushed",
    )
    UPDATED_COLUMNS = (
        "title",
        "author",
        "published_at",
        "content",
        "content_zh",
        "category_id",
    )
    LABEL = "news_articles"
    STAT_PREFIX = "app/news_articles"
    DEFAULT_DEAD_LETTER_DIR = DEFAULT_PG_DEAD_LETTER_DIR
    TRANSIENT_MARKERS = (
        "server closed the connection",
        "connection is closed",
        "connection lost",
        "deadlock detected",
        "could not serialize access",
        "terminating connection",
        "no connection to the server",
        "connection reset",
    )

    def __init__(
        self,
        enabled=False,
        host=DEFAULT_PG_HOST,
        port=DEFAULT_PG_PORT,
        database=DEFAULT_PG_DATABASE,
        user=DEFAULT_PG_USER,
        password="",
        table=DEFAULT_PG_TABLE,
        connect_timeout=10,
        batch_size=DEFAULT_PG_BATCH_SIZE,
        fail_on_error=True,
        dead_letter_dir=None,
        dead_letter_include_rows=False,
        max_failed_batches=20,
        retry_times=0,
        retry_backoff_seconds=1.0,
        transient_error_types=None,
        connection_factory=None,
        stats=None,
    ):
        super().__init__(
            enabled=enabled,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            table=table,
            connect_timeout=connect_timeout,
            batch_size=batch_size,
            fail_on_error=fail_on_error,
            dead_letter_dir=dead_letter_dir,
            dead_letter_include_rows=dead_letter_include_rows,
            max_failed_batches=max_failed_batches,
            retry_times=retry_times,
            retry_backoff_seconds=retry_backoff_seconds,
            transient_error_types=transient_error_types,
            connection_factory=connection_factory,
            stats=stats,
        )
        self._source_id_cache = {}

    @classmethod
    def from_settings(cls, settings, stats=None):
        return cls(
            enabled=settings.getbool("PG_ENABLED", False),
            host=settings.get("PG_HOST", DEFAULT_PG_HOST),
            port=settings.getint("PG_PORT", DEFAULT_PG_PORT),
            database=settings.get("PG_DATABASE", DEFAULT_PG_DATABASE),
            user=settings.get("PG_USER", DEFAULT_PG_USER),
            password=settings.get("PG_PASSWORD", ""),
            table=settings.get("PG_TABLE", DEFAULT_PG_TABLE),
            connect_timeout=settings.getint("PG_CONNECT_TIMEOUT", 10),
            batch_size=settings.getint("PG_BATCH_SIZE", DEFAULT_PG_BATCH_SIZE),
            fail_on_error=settings.getbool("PG_FAIL_ON_ERROR", True),
            dead_letter_dir=settings.get("PG_DEAD_LETTER_DIR"),
            dead_letter_include_rows=settings.getbool("PG_DEAD_LETTER_INCLUDE_ROWS", False),
            max_failed_batches=settings.getint("PG_MAX_FAILED_BATCHES", 20),
            retry_times=settings.getint("PG_RETRY_TIMES", 0),
            retry_backoff_seconds=settings.getfloat("PG_RETRY_BACKOFF_SECONDS", 1.0),
            stats=stats,
        )

    @classmethod
    def from_crawler(cls, crawler):
        return cls.from_settings(crawler.settings, stats=getattr(crawler, "stats", None))

    @classmethod
    def _quote_identifier(cls, value):
        text = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+", text):
            raise ValueError(f"Invalid PostgreSQL identifier: {value!r}")
        return f'"{text}"'

    @classmethod
    def build_insert_sql(cls, table):
        quoted_table = cls._quote_identifier(table)
        columns = ", ".join(cls._quote_identifier(column) for column in cls.COLUMNS)
        placeholders = ", ".join(f"%({column})s" for column in cls.COLUMNS)
        updates = ", ".join(
            f"{cls._quote_identifier(column)}=EXCLUDED.{cls._quote_identifier(column)}"
            for column in cls.UPDATED_COLUMNS
        )
        return (
            f"INSERT INTO {quoted_table} ({columns}) VALUES ({placeholders}) "
            f'ON CONFLICT (md5(url)) DO UPDATE SET {updates}, '
            '"updated_at"=CURRENT_TIMESTAMP'
        )

    # -- Kafka message mapping ------------------------------------------------

    @staticmethod
    def unix_seconds_to_datetime(value):
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        if seconds <= 0:
            return None
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    @classmethod
    def map_message(cls, raw):
        """Map a Kafka JSON message to a ``news_articles`` row (without ``source_id``)."""
        title = _text(raw.get("title"))
        url = _text(raw.get("url"))
        content_md = _text(raw.get("content_md"))
        if not title or not url or not content_md:
            return None
        content = _text(raw.get("content")) or content_md
        return {
            "title": title,
            "url": url,
            "author": _text(raw.get("author")) or None,
            "published_at": cls.unix_seconds_to_datetime(raw.get("ctime")),
            "content": content,
            "content_zh": None,
            "category_id": None,
            "is_pushed": False,
        }

    def ingest_message(self, raw, spider=None):
        row = self.map_message(raw)
        if row is None:
            return None
        row["source_id"] = self.resolve_source_id(
            raw.get("site_name"), raw.get("domain"), row.get("url")
        )
        self.process_row(row, spider)
        return row

    # -- source resolution -------------------------------------------------------

    def resolve_source_id(self, site_name, domain, url):
        site_name = _text(site_name)
        domain = _text(domain)
        key = (site_name, domain)
        if key in self._source_id_cache:
            return self._source_id_cache[key]
        source_id = self._find_source_id(site_name, domain)
        if source_id is None:
            source_id = self._register_source(site_name, domain, url)
        self._source_id_cache[key] = source_id
        return source_id

    def _find_source_id(self, site_name, domain):
        if site_name:
            row = self._query_one(
                "SELECT id FROM data_sources WHERE name = %s ORDER BY id LIMIT 1",
                (site_name,),
            )
            if row:
                return row[0]
        if domain:
            row = self._query_one(
                "SELECT id FROM data_sources WHERE url LIKE %s ORDER BY id LIMIT 1",
                (f"%{domain}%",),
            )
            if row:
                return row[0]
        return None

    def _register_source(self, site_name, domain, url):
        name = site_name or domain or "未知来源"
        source_type = "wechat" if domain == "mp.weixin.qq.com" else "website"
        source_url = _text(url) or (f"https://{domain}" if domain else "")
        return self._insert_returning_id(
            "INSERT INTO data_sources (name, type, url, adapter, is_enabled) "
            "VALUES (%s, %s, %s, %s, true) RETURNING id",
            (name, source_type, source_url or None, "kafka"),
        )

    def _query_one(self, sql, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def _insert_returning_id(self, sql, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        self.connection.commit()
        return row[0] if row else None

    # -- connection ------------------------------------------------------------

    def _create_connection(self, **kwargs):
        import psycopg2

        return psycopg2.connect(**kwargs)

    def _connection_kwargs(self):
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            "connect_timeout": self.connect_timeout,
        }
