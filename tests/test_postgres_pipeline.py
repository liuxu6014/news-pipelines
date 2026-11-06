import unittest

from app.pipelines import NewsArticlesPipeline


class NewsArticlesPipelineTests(unittest.TestCase):
    def test_build_insert_sql_uses_md5_url_upsert(self):
        sql = NewsArticlesPipeline.build_insert_sql("news_articles")

        self.assertIn('INSERT INTO "news_articles"', sql)
        self.assertIn('ON CONFLICT (md5(url)) DO UPDATE', sql)
        self.assertIn('"source_id"', sql)
        self.assertIn('"title"', sql)
        self.assertIn('"updated_at"=CURRENT_TIMESTAMP', sql)

    def test_build_insert_sql_does_not_overwrite_url_source_id_or_is_pushed(self):
        sql = NewsArticlesPipeline.build_insert_sql("news_articles")

        self.assertNotIn('"url"=EXCLUDED."url"', sql)
        self.assertNotIn('"source_id"=EXCLUDED."source_id"', sql)
        self.assertNotIn('"is_pushed"=EXCLUDED."is_pushed"', sql)
        self.assertIn('"title"=EXCLUDED."title"', sql)

    def test_build_insert_sql_rejects_invalid_table_identifier(self):
        with self.assertRaises(ValueError):
            NewsArticlesPipeline.build_insert_sql("news-articles;drop")

    def test_unix_seconds_to_datetime_returns_utc_aware(self):
        value = NewsArticlesPipeline.unix_seconds_to_datetime(1793081280)

        self.assertIsNotNone(value.tzinfo)
        self.assertEqual(1793081280, int(value.timestamp()))

    def test_unix_seconds_to_datetime_rejects_invalid(self):
        self.assertIsNone(NewsArticlesPipeline.unix_seconds_to_datetime(0))
        self.assertIsNone(NewsArticlesPipeline.unix_seconds_to_datetime(-1))
        self.assertIsNone(NewsArticlesPipeline.unix_seconds_to_datetime("not-a-number"))

    def test_map_message_maps_fields_and_falls_back_to_content_md(self):
        row = NewsArticlesPipeline.map_message(
            {
                "title": " 标题 ",
                "url": "https://example.com/a",
                "content_md": "正文摘要",
                "ctime": 1793081280,
                "author": "作者",
            }
        )

        self.assertEqual("标题", row["title"])
        self.assertEqual("https://example.com/a", row["url"])
        self.assertEqual("作者", row["author"])
        self.assertEqual("正文摘要", row["content"])
        self.assertEqual(1793081280, int(row["published_at"].timestamp()))
        self.assertIsNone(row["content_zh"])
        self.assertIsNone(row["category_id"])
        self.assertFalse(row["is_pushed"])

    def test_map_message_returns_none_without_title_or_url(self):
        self.assertIsNone(NewsArticlesPipeline.map_message({"url": "https://example.com/a"}))
        self.assertIsNone(NewsArticlesPipeline.map_message({"title": "t"}))

    def test_connection_kwargs_use_dbname(self):
        pipeline = NewsArticlesPipeline(
            enabled=True,
            host="172.16.4.183",
            port=5432,
            database="pipesight",
            user="postgres",
            password="secret",
            connection_factory=lambda **kwargs: None,
        )

        kwargs = pipeline._connection_kwargs()

        self.assertEqual("172.16.4.183", kwargs["host"])
        self.assertEqual(5432, kwargs["port"])
        self.assertEqual("pipesight", kwargs["dbname"])
        self.assertEqual("postgres", kwargs["user"])
        self.assertEqual("secret", kwargs["password"])
        self.assertNotIn("charset", kwargs)
        self.assertNotIn("autocommit", kwargs)

    def test_resolve_source_id_registers_and_caches_when_no_match(self):
        class Cursor:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params=None):
                self.connection.queries.append((sql, params))

            def fetchone(self):
                return self.connection.fetchone_results.pop(0)

        class Connection:
            def __init__(self):
                self.queries = []
                self.commits = 0
                self.fetchone_results = []

            def cursor(self):
                return Cursor(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass

            def close(self):
                pass

        connection = Connection()
        # name lookup -> None, domain lookup -> None, insert -> (99,)
        connection.fetchone_results = [None, None, (99,)]
        pipeline = NewsArticlesPipeline(
            enabled=True,
            connection_factory=lambda **kwargs: connection,
        )
        pipeline.open_spider()

        self.assertEqual(99, pipeline.resolve_source_id("测试站点", "example.com", "https://example.com/a"))
        self.assertEqual(3, len(connection.queries))
        self.assertEqual(1, connection.commits)

        # Second call is served from cache without new queries.
        self.assertEqual(99, pipeline.resolve_source_id("测试站点", "example.com", "https://example.com/b"))
        self.assertEqual(3, len(connection.queries))

    def test_resolve_source_id_reuses_existing_by_name(self):
        class Cursor:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params=None):
                self.connection.queries.append((sql, params))

            def fetchone(self):
                return self.connection.fetchone_results.pop(0)

        class Connection:
            def __init__(self):
                self.queries = []
                self.commits = 0
                self.fetchone_results = []

            def cursor(self):
                return Cursor(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass

            def close(self):
                pass

        connection = Connection()
        connection.fetchone_results = [(13,)]
        pipeline = NewsArticlesPipeline(
            enabled=True,
            connection_factory=lambda **kwargs: connection,
        )
        pipeline.open_spider()

        self.assertEqual(13, pipeline.resolve_source_id("国家管网", "", "https://example.com/a"))
        self.assertEqual(1, len(connection.queries))
        self.assertEqual(0, connection.commits)


if __name__ == "__main__":
    unittest.main()
