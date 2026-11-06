"""Consume news messages from Kafka and upsert them into PostgreSQL.

Configuration comes from ``app/settings.py`` (which loads ``.env``) and can be
overridden with command-line flags. Use ``--dry-run`` to preview the mapped rows
without touching PostgreSQL.

Examples::

    # Preview 5 rows without writing to PostgreSQL.
    uv run python tools/kafka_consume.py --bootstrap-servers 172.16.4.182:9092 --dry-run --max-messages 5

    # Create the topic if missing, then consume continuously.
    uv run python tools/kafka_consume.py --ensure-topic
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipelines import NewsArticlesPipeline
from app.runtime.kafka_consumer import (
    DEFAULT_AUTO_OFFSET_RESET,
    DEFAULT_BOOTSTRAP_SERVERS,
    DEFAULT_COMMIT_INTERVAL_MSGS,
    DEFAULT_GROUP_ID,
    DEFAULT_TOPIC,
    KafkaNewsConsumer,
)
from app.runtime.runner import configure_output_streams


def _load_settings():
    from scrapy.settings import Settings

    settings = Settings()
    settings.setmodule("app.settings")
    return settings


def _setup_logging():
    configure_output_streams()
    logger = logging.getLogger("app.runtime.kafka_consumer")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)sZ %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


def parse_args(argv=None):
    settings = _load_settings()
    parser = argparse.ArgumentParser(description="Consume news from Kafka into PostgreSQL.")
    parser.add_argument(
        "--bootstrap-servers",
        default=settings.get("KAFKA_BOOTSTRAP_SERVERS") or DEFAULT_BOOTSTRAP_SERVERS,
        help="Kafka bootstrap servers, e.g. host:9092",
    )
    parser.add_argument("--topic", default=settings.get("KAFKA_TOPIC") or DEFAULT_TOPIC)
    parser.add_argument("--group-id", default=settings.get("KAFKA_GROUP_ID") or DEFAULT_GROUP_ID)
    parser.add_argument(
        "--auto-offset-reset",
        choices=["earliest", "latest", "none"],
        default=settings.get("KAFKA_AUTO_OFFSET_RESET") or DEFAULT_AUTO_OFFSET_RESET,
    )
    parser.add_argument("--security-protocol", default=settings.get("KAFKA_SECURITY_PROTOCOL") or None)
    parser.add_argument("--sasl-mechanism", default=settings.get("KAFKA_SASL_MECHANISM") or None)
    parser.add_argument("--sasl-username", default=settings.get("KAFKA_SASL_USERNAME") or None)
    parser.add_argument("--sasl-password", default=settings.get("KAFKA_SASL_PASSWORD") or None)
    parser.add_argument(
        "--commit-interval-msgs",
        type=int,
        default=settings.getint("KAFKA_COMMIT_INTERVAL_MSGS", DEFAULT_COMMIT_INTERVAL_MSGS),
    )
    parser.add_argument("--max-messages", type=int, default=None, help="consume at most N messages, then exit")
    parser.add_argument("--dry-run", action="store_true", help="map and log rows without writing to PostgreSQL")
    parser.add_argument("--ensure-topic", action="store_true", help="create the topic if it does not exist")
    parser.add_argument("--partitions", type=int, default=1, help="partitions when creating the topic")
    parser.add_argument("--replication-factor", type=int, default=1, help="replication factor when creating the topic")
    return parser.parse_args(argv), settings


def ensure_topic(args, logger):
    from kafka import KafkaAdminClient
    from kafka.admin import NewTopic
    from kafka.errors import TopicAlreadyExistsError

    admin = KafkaAdminClient(bootstrap_servers=args.bootstrap_servers)
    try:
        admin.create_topics(
            [
                NewTopic(
                    name=args.topic,
                    num_partitions=args.partitions,
                    replication_factor=args.replication_factor,
                )
            ]
        )
        logger.info("KAFKA_TOPIC_CREATED topic=%s", args.topic)
    except TopicAlreadyExistsError:
        logger.info("KAFKA_TOPIC_EXISTS topic=%s", args.topic)
    finally:
        admin.close()


def main(argv=None):
    args, settings = parse_args(argv)
    logger = _setup_logging()

    if args.ensure_topic:
        ensure_topic(args, logger)

    pipeline = None
    if not args.dry_run:
        pipeline = NewsArticlesPipeline.from_settings(settings)

    consumer = KafkaNewsConsumer(
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
        group_id=args.group_id,
        auto_offset_reset=args.auto_offset_reset,
        commit_interval_msgs=args.commit_interval_msgs,
        security_protocol=args.security_protocol,
        sasl_mechanism=args.sasl_mechanism,
        sasl_username=args.sasl_username,
        sasl_password=args.sasl_password,
        pipeline=pipeline,
        logger=logger,
    )

    processed, skipped = consumer.run(max_messages=args.max_messages, dry_run=args.dry_run)
    logger.info("KAFKA_CONSUME_SUMMARY processed=%s skipped=%s", processed, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
