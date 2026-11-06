"""Scrapy extension for spider-monitor 0.2.2."""

import time
import uuid
from importlib.util import find_spec
from urllib.parse import urlparse

from itemadapter import ItemAdapter
from scrapy import signals
from scrapy.exceptions import NotConfigured

from app.monitors.quality_rules import QualityThresholds, evaluate_quality

DEFAULT_MONITOR_ITEM_FIELDS = (
    "canonical_url",
    "url_hash",
    "content_hash",
    "source",
    "source_site",
    "source_category",
    "domain",
    "publish_time",
)


class SpiderMonitorExtension:
    """Report crawl lifecycle and item events to spider-monitor."""

    def __init__(
        self,
        project="scrapy-template",
        environment="local",
        endpoint="",
        fail_on_error=False,
        owner="",
        owner_email="",
        owner_phone="",
        owner_team="",
        stats=None,
        monitor_factory=None,
        run_id_factory=None,
        min_items=0,
        max_dropped=0,
        max_spider_errors=0,
        max_db_errors=0,
        fail_on_quality_error=False,
        item_field_allowlist=None,
    ):
        self.project = project
        self.environment = environment
        self.endpoint = endpoint
        self.fail_on_error = fail_on_error
        self.owner = owner
        self.owner_email = owner_email
        self.owner_phone = owner_phone
        self.owner_team = owner_team
        self.stats = stats
        self.monitor_factory = monitor_factory or self._create_monitor
        self.run_id_factory = run_id_factory or self._default_run_id
        self.quality_thresholds = QualityThresholds(
            min_items=int(min_items),
            max_dropped=int(max_dropped),
            max_spider_errors=int(max_spider_errors),
            max_db_errors=int(max_db_errors),
        )
        self.fail_on_quality_error = fail_on_quality_error
        self.item_field_allowlist = self._normalize_field_allowlist(item_field_allowlist)
        self.monitors = {}
        self.run_ids = {}
        self.started_at = {}
        self.local_counts = {}

    @classmethod
    def from_crawler(cls, crawler, monitor_factory=None):
        settings = crawler.settings
        if not settings.getbool("SPIDER_MONITOR_ENABLED", True):
            raise NotConfigured("SPIDER_MONITOR_ENABLED is false")
        endpoint = settings.get("SPIDER_MONITOR_ENDPOINT", "")
        environment = settings.get("SPIDER_MONITOR_ENV", "local")
        cls._validate_endpoint(endpoint, environment)
        if find_spec("spider_monitor") is None:
            raise NotConfigured("spider_monitor package is not installed")
        extension = cls(
            project=settings.get("SPIDER_MONITOR_PROJECT", "scrapy-template"),
            environment=environment,
            endpoint=endpoint,
            fail_on_error=settings.getbool("SPIDER_MONITOR_FAIL_ON_ERROR", False),
            owner=settings.get("SPIDER_MONITOR_OWNER", ""),
            owner_email=settings.get("SPIDER_MONITOR_OWNER_EMAIL", ""),
            owner_phone=settings.get("SPIDER_MONITOR_OWNER_PHONE", ""),
            owner_team=settings.get("SPIDER_MONITOR_OWNER_TEAM", ""),
            stats=getattr(crawler, "stats", None),
            monitor_factory=monitor_factory,
            min_items=settings.getint("SPIDER_MONITOR_MIN_ITEMS", 0),
            max_dropped=settings.getint("SPIDER_MONITOR_MAX_DROPPED", 0),
            max_spider_errors=settings.getint("SPIDER_MONITOR_MAX_SPIDER_ERRORS", 0),
            max_db_errors=settings.getint("SPIDER_MONITOR_MAX_DB_ERRORS", 0),
            fail_on_quality_error=settings.getbool("SPIDER_MONITOR_FAIL_ON_QUALITY_ERROR", False),
            item_field_allowlist=settings.getlist("SPIDER_MONITOR_FIELD_ALLOWLIST", list(DEFAULT_MONITOR_ITEM_FIELDS)),
        )
        crawler.signals.connect(extension.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(extension.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(extension.item_dropped, signal=signals.item_dropped)
        crawler.signals.connect(extension.spider_error, signal=signals.spider_error)
        crawler.signals.connect(extension.spider_closed, signal=signals.spider_closed)
        return extension

    @staticmethod
    def _validate_endpoint(endpoint, environment):
        endpoint = str(endpoint or "").strip()
        environment = str(environment or "").strip().lower()
        if not endpoint or environment in {"", "local", "dev", "development", "test"}:
            return
        if urlparse(endpoint).scheme.lower() != "https":
            raise NotConfigured("SPIDER_MONITOR_ENDPOINT must use HTTPS outside local environments")

    @staticmethod
    def _default_run_id(spider):
        return f"{spider.name}-{uuid.uuid4().hex[:12]}"

    def _create_monitor(self, config):
        from spider_monitor import SpiderMonitor

        labels = {
            "project": config["project"],
            "spider": config["spider"],
            "environment": config["environment"],
        }
        return SpiderMonitor(
            name=f"{config['project']}:{config['spider']}",
            labels=labels,
            report_endpoint=config.get("endpoint") or None,
            client_id=config["run_id"],
            owner=config.get("owner") or None,
            owner_email=config.get("owner_email") or None,
            owner_phone=config.get("owner_phone") or None,
            owner_team=config.get("owner_team") or None,
            run_type="scrapy",
            trigger_source=config["environment"],
        )

    def spider_opened(self, spider):
        run_id = self.run_id_factory(spider)
        config = {
            "project": self.project,
            "environment": self.environment,
            "endpoint": self.endpoint,
            "spider": spider.name,
            "run_id": run_id,
            "owner": self.owner,
            "owner_email": self.owner_email,
            "owner_phone": self.owner_phone,
            "owner_team": self.owner_team,
        }
        self.run_ids[spider.name] = run_id
        self.started_at[spider.name] = time.monotonic()
        self.local_counts[spider.name] = {"item_dropped_count": 0, "spider_error_count": 0}
        try:
            self.monitors[spider.name] = self.monitor_factory(config)
            self._call_monitor(spider, "start_run", run_type="scrapy", trigger_source=self.environment, run_id=run_id)
        except Exception as exc:
            self._handle_error(spider, exc)

    def item_scraped(self, item, response, spider):
        item_data = self._item_dict(item)
        fields = self._allowed_item_fields(item_data)
        canonical_url = fields.get("canonical_url") or item_data.get("canonical_url")
        self._call_monitor(
            spider,
            "record_item",
            item_type="scrapy_item",
            item_id=canonical_url or item_data.get("title") or spider.name,
            fields=fields,
            source_url=canonical_url,
            spider_name=spider.name,
            run_id=self.run_ids.get(spider.name),
        )

    def item_dropped(self, item, response, exception, spider):
        self._count(spider, "item_dropped_count")
        self._call_monitor(
            spider,
            "record_error",
            error=exception,
            extra={"spider": spider.name, "run_id": self.run_ids.get(spider.name), "error_type": "item_dropped"},
        )

    def spider_error(self, failure, response, spider):
        self._count(spider, "spider_error_count")
        self._call_monitor(
            spider,
            "record_error",
            error=self._failure_error(failure),
            extra={"spider": spider.name, "run_id": self.run_ids.get(spider.name), "error_type": "spider_error"},
        )

    def spider_closed(self, spider, reason):
        summary = self._build_summary(spider, reason)
        for issue in summary["quality_issues"]:
            self._call_monitor(
                spider,
                "record_error",
                error=RuntimeError(issue["reason"]),
                extra={
                    "spider": spider.name,
                    "run_id": summary.get("run_id"),
                    "error_type": "quality_issue",
                    "quality_issue": issue,
                },
            )
        self._call_monitor(
            spider,
            "finish_run",
            status=summary["status"],
            exit_code=0 if summary["status"] == "success" else 1,
            error=None if summary["status"] == "success" else reason,
        )
        self._call_monitor(spider, "flush")
        self._call_monitor(spider, "shutdown")
        self.monitors.pop(spider.name, None)
        self.started_at.pop(spider.name, None)
        self.local_counts.pop(spider.name, None)
        self.run_ids.pop(spider.name, None)
        if summary["quality_issues"] and self.fail_on_quality_error:
            raise RuntimeError("Spider monitor quality failed: " + ",".join(issue["reason"] for issue in summary["quality_issues"]))

    def _build_summary(self, spider, reason):
        stats = self._stats()
        local = self.local_counts.get(spider.name, {})
        started = self.started_at.get(spider.name)
        duration = round(time.monotonic() - started, 3) if started is not None else None
        summary = {
            "project": self.project,
            "environment": self.environment,
            "spider": spider.name,
            "run_id": self.run_ids.get(spider.name),
            "status": "success" if reason in ("finished", "shutdown", "closespider_itemcount", "closespider_timeout") else "failed",
            "finish_reason": reason,
            "duration_seconds": duration,
            "item_scraped_count": self._int_stat(stats, "item_scraped_count", 0),
            "item_dropped_count": self._int_stat(stats, "item_dropped_count", local.get("item_dropped_count", 0)),
            "spider_error_count": self._int_stat(stats, "app/spider_error_count", local.get("spider_error_count", 0)),
            "db_error_count": self._int_stat(stats, "app/mysql/write_failed", 0),
        }
        summary["quality_issues"] = evaluate_quality(summary, self.quality_thresholds)
        if summary["quality_issues"]:
            summary["status"] = "failed"
        return summary

    def _stats(self):
        if self.stats and hasattr(self.stats, "get_stats"):
            return self.stats.get_stats()
        return {}

    @staticmethod
    def _int_stat(stats, key, default):
        try:
            return int(stats.get(key, default) or 0)
        except (TypeError, ValueError):
            return int(default or 0)

    def _count(self, spider, key):
        self.local_counts.setdefault(spider.name, {}).setdefault(key, 0)
        self.local_counts[spider.name][key] += 1
        if self.stats and hasattr(self.stats, "inc_value"):
            self.stats.inc_value(f"app/{key}")

    def _call_monitor(self, spider, method_name, **kwargs):
        monitor = self.monitors.get(spider.name)
        if monitor is None:
            return None
        method = getattr(monitor, method_name, None)
        if not callable(method):
            return None
        try:
            return method(**kwargs)
        except Exception as exc:
            self._handle_error(spider, exc)
            return None

    def _handle_error(self, spider, exc):
        logger = getattr(spider, "logger", None)
        if logger:
            logger.error("spider-monitor error: %s", exc)
        if self.fail_on_error:
            raise exc

    @staticmethod
    def _failure_error(failure):
        if isinstance(failure, BaseException):
            return failure
        if hasattr(failure, "value") and isinstance(failure.value, BaseException):
            return failure.value
        return RuntimeError(str(failure))

    @staticmethod
    def _item_dict(item):
        try:
            return ItemAdapter(item).asdict()
        except Exception:
            try:
                return dict(item)
            except Exception:
                return {"value": str(item)}

    @staticmethod
    def _normalize_field_allowlist(fields):
        if fields is None:
            fields = DEFAULT_MONITOR_ITEM_FIELDS
        if isinstance(fields, str):
            fields = fields.split(",")
        return tuple(str(field).strip() for field in fields if str(field).strip())

    def _allowed_item_fields(self, item_data):
        return {field: item_data[field] for field in self.item_field_allowlist if field in item_data}
