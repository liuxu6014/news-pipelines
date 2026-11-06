import unittest
from types import SimpleNamespace

from scrapy.exceptions import NotConfigured
from scrapy.settings import Settings
from scrapy.signalmanager import SignalManager

from app.extensions.spider_monitor import SpiderMonitorExtension


class SpiderMonitorExtensionTests(unittest.TestCase):
    def test_call_monitor_does_not_retry_typeerror_with_wrong_arguments(self):
        class BrokenMonitor:
            def __init__(self):
                self.calls = 0

            def record_item(self, **kwargs):
                self.calls += 1
                raise TypeError("internal sdk error")

        class Spider:
            name = "example"
            logger = None

        monitor = BrokenMonitor()
        extension = SpiderMonitorExtension(fail_on_error=True)
        extension.monitors["example"] = monitor

        with self.assertRaisesRegex(TypeError, "internal sdk error"):
            extension._call_monitor(Spider(), "record_item", item_type="item")

        self.assertEqual(1, monitor.calls)

    def test_item_scraped_reports_only_allowlisted_fields(self):
        class RecorderMonitor:
            def __init__(self):
                self.recorded = None

            def record_item(self, **kwargs):
                self.recorded = kwargs

        class Spider:
            name = "example"
            logger = None

        monitor = RecorderMonitor()
        extension = SpiderMonitorExtension(item_field_allowlist=["canonical_url", "url_hash", "source_site"])
        extension.monitors["example"] = monitor
        extension.run_ids["example"] = "run-1"

        extension.item_scraped(
            {
                "canonical_url": "https://example.com/news",
                "url": "https://example.com/news?utm_source=x",
                "url_hash": "hash",
                "source_site": "example",
                "content": "sensitive body",
                "raw_item": "raw sensitive body",
            },
            response=None,
            spider=Spider(),
        )

        self.assertEqual(
            {
                "canonical_url": "https://example.com/news",
                "url_hash": "hash",
                "source_site": "example",
            },
            monitor.recorded["fields"],
        )
        self.assertNotIn("content", monitor.recorded["fields"])
        self.assertNotIn("raw_item", monitor.recorded["fields"])
        self.assertEqual("run-1", monitor.recorded["run_id"])

    def test_item_scraped_does_not_forward_raw_source_url(self):
        class RecorderMonitor:
            def __init__(self):
                self.recorded = None

            def record_item(self, **kwargs):
                self.recorded = kwargs

        class Spider:
            name = "example"
            logger = None

        monitor = RecorderMonitor()
        extension = SpiderMonitorExtension(item_field_allowlist=["canonical_url", "url_hash"])
        extension.monitors["example"] = monitor
        extension.run_ids["example"] = "run-1"

        extension.item_scraped(
            {
                "canonical_url": "https://example.com/news",
                "url": "https://example.com/news?utm_source=x&id=2",
                "url_hash": "hash",
            },
            response=None,
            spider=Spider(),
        )

        self.assertEqual("https://example.com/news", monitor.recorded["source_url"])
        self.assertEqual("https://example.com/news", monitor.recorded["item_id"])

    def test_from_crawler_rejects_http_monitor_endpoint_outside_local(self):
        crawler = SimpleNamespace(
            settings=Settings(
                {
                    "SPIDER_MONITOR_ENABLED": True,
                    "SPIDER_MONITOR_ENV": "prod",
                    "SPIDER_MONITOR_ENDPOINT": "http://monitor.example.com/report",
                }
            ),
            signals=SignalManager(),
            stats=None,
        )

        with self.assertRaisesRegex(NotConfigured, "HTTPS"):
            SpiderMonitorExtension.from_crawler(crawler)
