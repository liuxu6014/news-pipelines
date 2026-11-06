import unittest

from app.pipelines import NewsArticlesPipeline
from app.runtime.kafka_consumer import KafkaNewsConsumer


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.connection.queries.append((sql, params))

    def executemany(self, sql, rows):
        self.connection.queries.append((sql, list(rows)))

    def fetchone(self):
        return self.connection.fetchone_results.pop(0)


class FakeConnection:
    def __init__(self):
        self.queries = []
        self.commits = 0
        self.fetchone_results = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


class KafkaNewsConsumerTests(unittest.TestCase):
    def test_run_raises_when_pipeline_disabled(self):
        consumer = KafkaNewsConsumer(pipeline=None)

        with self.assertRaises(RuntimeError):
            consumer.run(dry_run=False)

    def test_ingest_message_resolves_source_and_queues_row(self):
        connection = FakeConnection()
        # name lookup -> None, domain lookup -> None, register -> id 42
        connection.fetchone_results = [None, None, (42,)]
        pipeline = NewsArticlesPipeline(
            enabled=True,
            connection_factory=lambda **kwargs: connection,
            batch_size=10,
        )
        pipeline.open_spider()

        row = pipeline.ingest_message(
            {
                "title": "标题",
                "url": "https://example.com/a",
                "content": "正文",
                "content_md": "**正文**",
                "ctime": 1793081280,
                "site_name": "测试站点",
                "domain": "example.com",
            }
        )

        self.assertIsNotNone(row)
        self.assertEqual(42, row["source_id"])
        self.assertEqual(1, len(pipeline.pending_rows))

        pipeline.close_spider()

    def test_map_message_requires_content_md(self):
        base = {"title": "标题", "url": "https://example.com/a"}

        # 缺 content_md 直接跳过（即使有纯文本 content）
        self.assertIsNone(NewsArticlesPipeline.map_message({**base, "content": "正文"}))

        # 有 content_md 即可映射；纯文本 content 缺省时回退 content_md
        row = NewsArticlesPipeline.map_message({**base, "content_md": "**正文**"})
        self.assertIsNotNone(row)
        self.assertEqual("**正文**", row["content"])


if __name__ == "__main__":
    unittest.main()
