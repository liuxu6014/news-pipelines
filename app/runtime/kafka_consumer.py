"""Kafka -> PostgreSQL ``news_articles`` consumer.

Reads news messages from a Kafka topic and upserts them into the
``news_articles`` table of the ``pipesight`` PostgreSQL database via
:class:`app.pipelines.NewsArticlesPipeline`. Each message's ``source_id`` is
resolved against ``data_sources`` (matched by ``site_name`` / ``domain``, or
registered on first sight). Rows dedupe on the unique ``md5(url)`` index.

Expected message shape (JSON object)::

    {
        "title": str,           # 必填
        "url": str,             # 必填
        "content_md": str,      # 必填（Markdown 正文）；content 为空时也用它兜底
        "content": str,         # 可选，纯文本；缺省回退 content_md
        "ctime": int,           # Unix seconds; mapped to published_at (timestamptz)
        "author": str,
        "domain": str | None,
        "domain_id": str | int | None,
        "image_url": str,
        "site_name": str,
        # ... extra fields are ignored
    }
"""

import json
import logging

from kafka import KafkaConsumer
from kafka.structs import OffsetAndMetadata, TopicPartition

from app.pipelines import NewsArticlesPipeline

LOGGER_NAME = "app.runtime.kafka_consumer"
DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"
DEFAULT_TOPIC = "news_pipeline"
DEFAULT_GROUP_ID = "news-pipelines-rss-consumer"
DEFAULT_AUTO_OFFSET_RESET = "earliest"
DEFAULT_COMMIT_INTERVAL_MSGS = 100


class KafkaNewsConsumer:
    """Consume news from Kafka and upsert into ``news_articles`` with at-least-once delivery."""

    def __init__(
        self,
        bootstrap_servers=DEFAULT_BOOTSTRAP_SERVERS,
        topic=DEFAULT_TOPIC,
        group_id=DEFAULT_GROUP_ID,
        auto_offset_reset=DEFAULT_AUTO_OFFSET_RESET,
        commit_interval_msgs=DEFAULT_COMMIT_INTERVAL_MSGS,
        security_protocol=None,
        sasl_mechanism=None,
        sasl_username=None,
        sasl_password=None,
        pipeline=None,
        logger=None,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.group_id = group_id
        self.auto_offset_reset = auto_offset_reset
        self.commit_interval_msgs = max(1, int(commit_interval_msgs or 1))
        self.security_protocol = security_protocol
        self.sasl_mechanism = sasl_mechanism
        self.sasl_username = sasl_username
        self.sasl_password = sasl_password
        self.pipeline = pipeline
        self.logger = logger or logging.getLogger(LOGGER_NAME)
        self.processed = 0
        self.skipped = 0

    def _build_consumer(self):
        kwargs = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": self.group_id,
            "auto_offset_reset": self.auto_offset_reset,
            "enable_auto_commit": False,
        }
        if self.security_protocol:
            kwargs["security_protocol"] = self.security_protocol
            if self.sasl_mechanism:
                kwargs["sasl_mechanism"] = self.sasl_mechanism
                kwargs["sasl_plain_username"] = self.sasl_username
                kwargs["sasl_plain_password"] = self.sasl_password
        return KafkaConsumer(self.topic, **kwargs)

    def run(self, max_messages=None, dry_run=False):
        """Consume until interrupted or ``max_messages`` records are processed.

        Offsets are committed only after the matching SQL batch has been
        flushed, so a crash mid-batch replays the uncommitted records.
        """
        pipe = self.pipeline
        if not dry_run and (pipe is None or not pipe.enabled):
            raise RuntimeError(
                "news_articles pipeline is not enabled; set PG_ENABLED=1 or run with --dry-run"
            )

        consumer = self._build_consumer()
        max_records = self.commit_interval_msgs
        if not dry_run:
            pipe.open_spider(None)
        processed_offsets = {}
        try:
            idle_polls = 0
            done = False
            while not done:
                records = consumer.poll(timeout_ms=1000, max_records=max_records)
                if not records:
                    # A bounded run exits once the topic goes quiet. The first
                    # polls of a fresh group are empty while the consumer joins
                    # and partitions are assigned, so allow several seconds.
                    idle_polls += 1
                    if max_messages is not None and idle_polls >= 10:
                        break
                    continue
                idle_polls = 0
                for _partition, messages in records.items():
                    for message in messages:
                        try:
                            raw = json.loads(message.value.decode("utf-8"))
                            row = NewsArticlesPipeline.map_message(raw) if dry_run else pipe.ingest_message(raw)
                        except Exception as exc:
                            self.skipped += 1
                            self.logger.warning(
                                "KAFKA_SKIP topic=%s partition=%s offset=%s error=%s",
                                message.topic,
                                message.partition,
                                message.offset,
                                exc,
                            )
                            continue
                        if row is None:
                            self.skipped += 1
                            self.logger.warning(
                                "KAFKA_SKIP_EMPTY topic=%s partition=%s offset=%s reason=missing_title_or_url",
                                message.topic,
                                message.partition,
                                message.offset,
                            )
                            continue
                        self.processed += 1
                        processed_offsets[TopicPartition(message.topic, message.partition)] = message.offset + 1
                        if dry_run:
                            self._log_preview(message, row)
                        if max_messages is not None and self.processed >= max_messages:
                            done = True
                            break
                    if done:
                        break

                if not dry_run:
                    pipe.flush(None)
                    self._commit(consumer, processed_offsets)
        finally:
            if not dry_run:
                pipe.flush(None)
                try:
                    self._commit(consumer, processed_offsets)
                except Exception as exc:
                    self.logger.warning("KAFKA_COMMIT_FAILED error=%s", exc)
                pipe.close_spider(None)
            consumer.close()
        return self.processed, self.skipped

    @staticmethod
    def _commit(consumer, processed_offsets):
        if not processed_offsets:
            return
        offsets = {
            topic_partition: OffsetAndMetadata(offset, None)
            for topic_partition, offset in processed_offsets.items()
        }
        consumer.commit(offsets)
        processed_offsets.clear()

    def _log_preview(self, message, row):
        self.logger.info(
            "KAFKA_DRY_RUN topic=%s partition=%s offset=%s url=%s title=%s published_at=%s source_id=%s",
            message.topic,
            message.partition,
            message.offset,
            row.get("url"),
            str(row.get("title") or "")[:80],
            row.get("published_at"),
            row.get("source_id"),
        )
