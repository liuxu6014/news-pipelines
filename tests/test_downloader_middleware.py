import unittest

from scrapy import Request
from scrapy.exceptions import IgnoreRequest
from scrapy.http import TextResponse

from app.middlewares import (
    RotatingProxyMiddleware,
    ScrapyTemplateDownloaderMiddleware,
)


class ScrapyTemplateDownloaderMiddlewareTests(unittest.TestCase):
    def test_process_request_blocks_loopback_urls_when_ssrf_protection_is_enabled(self):
        middleware = ScrapyTemplateDownloaderMiddleware(ssrf_protection_enabled=True)

        with self.assertRaisesRegex(IgnoreRequest, "blocked_ssrf_target"):
            middleware.process_request(Request("http://127.0.0.1/admin"))

    def test_process_request_allows_configured_hosts(self):
        middleware = ScrapyTemplateDownloaderMiddleware(
            ssrf_protection_enabled=True,
            ssrf_allowed_hosts=["127.0.0.1"],
        )

        self.assertIsNone(middleware.process_request(Request("http://127.0.0.1/admin")))

    def test_rotating_proxy_is_sticky_per_host_and_rotates_on_failure(self):
        middleware = RotatingProxyMiddleware(
            [
                "http://user:pass@127.0.0.1:8001",
                "http://user:pass@127.0.0.1:8002",
            ],
            max_attempts=2,
        )
        first = Request("https://news.example.com/a")
        same_host = Request("https://news.example.com/b")
        other_host = Request("https://other.example.com/a")
        middleware.process_request(first)
        middleware.process_request(same_host)
        middleware.process_request(other_host)

        self.assertEqual(first.meta["proxy"], same_host.meta["proxy"])
        self.assertNotEqual(first.meta["proxy"], other_host.meta["proxy"])

        retry = middleware.process_response(
            first,
            TextResponse(url=first.url, status=503, request=first),
        )
        self.assertIsInstance(retry, Request)
        self.assertNotEqual(first.meta["proxy"], retry.meta["proxy"])
        self.assertEqual(1, retry.meta["proxy_attempt"])
