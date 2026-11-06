import json
import tempfile
import unittest
from pathlib import Path

from scrapy.exceptions import DropItem

from app.pipelines import MySQLItemPipeline


class MySQLItemPipelineTests(unittest.TestCase):
    def test_open_spider_does_not_execute_schema_sql(self):
        class Connection:
            executed = []

            def close(self):
                pass

        pipeline = MySQLItemPipeline(
            enabled=True,
            connection_factory=lambda **kwargs: Connection(),
            fail_on_error=True,
        )

        pipeline.open_spider()

        self.assertIsInstance(pipeline.connection, Connection)
        self.assertEqual([], Connection.executed)

    def test_build_insert_sql_uses_url_hash_upsert(self):
        sql = MySQLItemPipeline.build_insert_sql("rss_news")

        self.assertIn("INSERT INTO `rss_news`", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertIn("`url_hash`", sql)
        self.assertIn("`last_seen_at`=CURRENT_TIMESTAMP", sql)

    def test_build_insert_sql_rejects_invalid_table_identifier(self):
        with self.assertRaises(ValueError):
            MySQLItemPipeline.build_insert_sql("rss-news;drop")

    def test_to_row_normalizes_url_and_domain(self):
        row = MySQLItemPipeline.to_row(
            {
                "title": " Test ",
                "url": "HTTPS://WWW.Example.COM/news?utm_source=x&id=2",
                "content": "body",
                "category": "政策",
            }
        )

        self.assertEqual("Test", row["title"])
        self.assertEqual("https://www.example.com/news?id=2", row["canonical_url"])
        self.assertEqual("example.com", row["domain"])
        self.assertEqual("政策", row["source_category"])

    def test_to_row_rejects_items_without_url(self):
        with self.assertRaises(DropItem):
            MySQLItemPipeline.to_row({"title": "missing url"})

    def test_to_row_normalizes_publish_time_for_mysql_datetime(self):
        row = MySQLItemPipeline.to_row(
            {
                "url": "https://example.com/news",
                "publish_time": "2026-07-22T03:12:24Z",
            }
        )

        self.assertEqual("2026-07-22 03:12:24.000", row["publish_time"])

    def test_to_row_uses_none_for_unparseable_publish_time(self):
        row = MySQLItemPipeline.to_row(
            {
                "url": "https://example.com/news",
                "publish_time": "not a date",
            }
        )

        self.assertIsNone(row["publish_time"])

    def test_process_item_batches_mysql_writes(self):
        class Cursor:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                self.connection.operations.append(("execute", sql, params))

            def executemany(self, sql, rows):
                self.connection.operations.append(("executemany", sql, list(rows)))

        class Connection:
            def __init__(self):
                self.operations = []
                self.commits = 0
                self.closed = False

            def cursor(self):
                return Cursor(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass

            def close(self):
                self.closed = True

        connection = Connection()
        pipeline = MySQLItemPipeline(
            enabled=True,
            connection_factory=lambda **kwargs: connection,
            batch_size=2,
        )
        pipeline.open_spider()

        pipeline.process_item({"url": "https://example.com/a", "content": "a"})
        self.assertEqual([], connection.operations)

        pipeline.process_item({"url": "https://example.com/b", "content": "b"})
        self.assertEqual("executemany", connection.operations[0][0])
        self.assertEqual(1, connection.commits)
        self.assertEqual(2, pipeline.write_succeeded)

        pipeline.process_item({"url": "https://example.com/c", "content": "c"})
        pipeline.close_spider()

        self.assertEqual("execute", connection.operations[1][0])
        self.assertEqual(2, connection.commits)
        self.assertEqual(3, pipeline.write_succeeded)
        self.assertTrue(connection.closed)

    def test_flush_writes_sanitized_failed_batch_to_dead_letter(self):
        class Cursor:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                self.connection.operations.append(("execute", sql, params))

            def executemany(self, sql, rows):
                self.connection.operations.append(("executemany", sql, list(rows)))
                raise RuntimeError("write failed")

        class Connection:
            def __init__(self):
                self.operations = []
                self.commits = 0
                self.rollbacks = 0
                self.closed = False

            def cursor(self):
                return Cursor(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

            def close(self):
                self.closed = True

        class Spider:
            name = "example"
            logger = None

        with tempfile.TemporaryDirectory() as tmpdir:
            dead_letter_dir = Path(tmpdir) / "dead_letters"
            connection = Connection()
            pipeline = MySQLItemPipeline(
                enabled=True,
                connection_factory=lambda **kwargs: connection,
                batch_size=2,
                fail_on_error=False,
                dead_letter_dir=dead_letter_dir,
            )
            pipeline.open_spider(Spider())

            pipeline.process_item({"url": "https://example.com/a", "content": "a"}, spider=Spider())
            pipeline.process_item({"url": "https://example.com/b", "content": "b"}, spider=Spider())

            dead_letter_file = dead_letter_dir / "rss_news.jsonl"
            self.assertEqual([], pipeline.pending_rows)
            self.assertEqual(1, len(pipeline.failed_batches))
            self.assertNotIn("rows", pipeline.failed_batches[0])
            self.assertEqual(2, len(pipeline.failed_batches[0]["row_keys"]))
            self.assertEqual("example", pipeline.failed_batches[0]["spider"])
            self.assertEqual("write failed", pipeline.failed_batches[0]["error"])
            self.assertTrue(dead_letter_file.exists())
            lines = dead_letter_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            dead_letter = json.loads(lines[0])
            self.assertNotIn("rows", dead_letter)
            self.assertEqual(2, len(dead_letter["row_keys"]))
            self.assertEqual(0, connection.commits)
            self.assertEqual(1, connection.rollbacks)

    def test_failed_batches_keep_only_configured_in_memory_window(self):
        pipeline = MySQLItemPipeline(fail_on_error=False, max_failed_batches=2)

        for index in range(3):
            pipeline._store_failed_batch(None, [{"url_hash": str(index), "canonical_url": f"https://example.com/{index}"}], RuntimeError(str(index)))

        self.assertEqual(2, len(pipeline.failed_batches))
        self.assertEqual("1", pipeline.failed_batches[0]["error"])
        self.assertEqual("2", pipeline.failed_batches[1]["error"])

    def test_flush_retries_transient_failure_with_new_connection(self):
        class TransientMySQLError(Exception):
            pass

        class Cursor:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                self.connection.execute_calls += 1
                if self.connection.fail_first_execute:
                    self.connection.fail_first_execute = False
                    raise TransientMySQLError("server has gone away")

            def executemany(self, sql, rows):
                self.execute(sql, rows)

        class Connection:
            def __init__(self, fail_first_execute=False):
                self.fail_first_execute = fail_first_execute
                self.execute_calls = 0
                self.commits = 0
                self.rollbacks = 0
                self.closed = False

            def cursor(self):
                return Cursor(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

            def close(self):
                self.closed = True

        connections = [Connection(fail_first_execute=True), Connection()]

        pipeline = MySQLItemPipeline(
            enabled=True,
            connection_factory=lambda **kwargs: connections.pop(0),
            retry_times=1,
            retry_backoff_seconds=0,
            transient_error_types=(TransientMySQLError,),
        )
        pipeline.open_spider()

        pipeline.process_item({"url": "https://example.com/a"})
        pipeline.flush()

        self.assertEqual(1, pipeline.write_succeeded)
        self.assertEqual(1, pipeline.connection.commits)
        self.assertTrue(connections == [])
