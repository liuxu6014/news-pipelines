import unittest

from app.item_deduplication import canonicalize_url, item_hashes, sha256_text


class ItemDeduplicationTests(unittest.TestCase):
    def test_canonicalize_url_drops_tracking_params_sorts_query_and_removes_fragment(self):
        url = "HTTPS://Example.COM/news?id=2&utm_source=feed&a=1#comments"

        self.assertEqual(
            "https://example.com/news?a=1&id=2",
            canonicalize_url(url),
        )

    def test_item_hashes_uses_canonical_url_and_content(self):
        item = {
            "url": "https://example.com/news?utm_campaign=x&id=2",
            "summary": "hello",
        }

        hashes = item_hashes(item)

        self.assertEqual("https://example.com/news?id=2", hashes["canonical_url"])
        self.assertEqual(sha256_text("https://example.com/news?id=2"), hashes["url_hash"])
        self.assertEqual(sha256_text("hello"), hashes["content_hash"])
