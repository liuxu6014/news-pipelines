"""Scrapy 项目配置。"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default, min_value=None):
    raw_value = os.getenv(name)
    value = default if raw_value is None or str(raw_value).strip() == "" else raw_value
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer environment variable {name}={value!r}") from exc
    if min_value is not None and parsed < min_value:
        raise ValueError(f"Environment variable {name} must be >= {min_value}, got {parsed}")
    return parsed


def _env_list(name, default):
    raw_value = os.getenv(name)
    if raw_value is None or str(raw_value).strip() == "":
        return list(default)
    return [part.strip() for part in str(raw_value).split(",") if part.strip()]


BOT_NAME = "app"

SPIDER_MODULES = ["app.spiders"]
NEWSPIDER_MODULE = "app.spiders"

ROBOTSTXT_OBEY = True
USER_AGENT = "app (+https://example.com)"

CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = 8
DOWNLOAD_DELAY = 0.5
DOWNLOAD_TIMEOUT = 30

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0
AUTOTHROTTLE_DEBUG = False

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [408, 429, 500, 502, 503, 504]

HTTPCACHE_ENABLED = _env_bool("HTTPCACHE_ENABLED", False)
HTTPCACHE_EXPIRATION_SECS = 0
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [503, 504]
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

SPIDER_MIDDLEWARES = {
    "app.middlewares.ScrapyTemplateSpiderMiddleware": 543,
}

DOWNLOADER_MIDDLEWARES = {
    "app.middlewares.RotatingProxyMiddleware": 560,
    "app.middlewares.ScrapyTemplateDownloaderMiddleware": 543,
    "app.middlewares.PlaywrightRenderMiddleware": 535,
    "app.middlewares.CurlCffiDownloaderMiddleware": 530,
}

SSRF_PROTECTION_ENABLED = _env_bool("SSRF_PROTECTION_ENABLED", True)
SSRF_ALLOWED_HOSTS = _env_list("SSRF_ALLOWED_HOSTS", [])
# 需要用 Chrome TLS 指纹（curl_cffi）请求的主机白名单，命中才走 curl_cffi，其余走默认下载器。
CURL_CFFI_HOSTS = _env_list("CURL_CFFI_HOSTS", [])
CURL_CFFI_CONCURRENCY_PER_HOST = _env_int("CURL_CFFI_CONCURRENCY_PER_HOST", 2, min_value=1)
CURL_CFFI_DELAY_SECONDS = float(os.getenv("CURL_CFFI_DELAY_SECONDS", "0.5"))
# 必须用真实浏览器渲染才能拿到正文的主机白名单（瑞数/Incapsula/Cloudflare/纯 JS SPA）。
PLAYWRIGHT_HOSTS = _env_list("PLAYWRIGHT_HOSTS", [])
PLAYWRIGHT_CONCURRENCY_PER_HOST = _env_int("PLAYWRIGHT_CONCURRENCY_PER_HOST", 1, min_value=1)
PLAYWRIGHT_CHANNEL = os.getenv("PLAYWRIGHT_CHANNEL", "chrome")

EXTENSIONS = {
    "app.extensions.spider_monitor.SpiderMonitorExtension": 500,
}

ITEM_PIPELINES = {
    "app.pipelines.ScrapyTemplatePipeline": 300,
    "app.pipelines.MySQLItemPipeline": 850,
}

SPIDER_MONITOR_ENABLED = _env_bool("SPIDER_MONITOR_ENABLED", True)
SPIDER_MONITOR_PROJECT = os.getenv("SPIDER_MONITOR_PROJECT", BOT_NAME)
SPIDER_MONITOR_ENV = os.getenv("SPIDER_MONITOR_ENV", "local")
SPIDER_MONITOR_ENDPOINT = os.getenv("SPIDER_MONITOR_ENDPOINT", "")
SPIDER_MONITOR_FAIL_ON_ERROR = _env_bool("SPIDER_MONITOR_FAIL_ON_ERROR", False)
SPIDER_MONITOR_OWNER = os.getenv("SPIDER_MONITOR_OWNER", "")
SPIDER_MONITOR_OWNER_EMAIL = os.getenv("SPIDER_MONITOR_OWNER_EMAIL", "")
SPIDER_MONITOR_OWNER_PHONE = os.getenv("SPIDER_MONITOR_OWNER_PHONE", "")
SPIDER_MONITOR_OWNER_TEAM = os.getenv("SPIDER_MONITOR_OWNER_TEAM", "")
SPIDER_MONITOR_MIN_ITEMS = _env_int("SPIDER_MONITOR_MIN_ITEMS", 0, min_value=0)
SPIDER_MONITOR_MAX_DROPPED = _env_int("SPIDER_MONITOR_MAX_DROPPED", 0, min_value=0)
SPIDER_MONITOR_MAX_SPIDER_ERRORS = _env_int("SPIDER_MONITOR_MAX_SPIDER_ERRORS", 0, min_value=0)
SPIDER_MONITOR_MAX_DB_ERRORS = _env_int("SPIDER_MONITOR_MAX_DB_ERRORS", 0, min_value=0)
SPIDER_MONITOR_FAIL_ON_QUALITY_ERROR = _env_bool("SPIDER_MONITOR_FAIL_ON_QUALITY_ERROR", False)
SPIDER_MONITOR_FIELD_ALLOWLIST = _env_list(
    "SPIDER_MONITOR_FIELD_ALLOWLIST",
    [
        "canonical_url",
        "url_hash",
        "content_hash",
        "source",
        "source_site",
        "source_category",
        "domain",
        "publish_time",
    ],
)

MYSQL_ENABLED = _env_bool("MYSQL_ENABLED", False)
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = _env_int("MYSQL_PORT", 3306, min_value=1)
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "crawler")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_TABLE = os.getenv("MYSQL_TABLE", "rss_news")
MYSQL_CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")
MYSQL_CONNECT_TIMEOUT = _env_int("MYSQL_CONNECT_TIMEOUT", 10, min_value=1)
MYSQL_BATCH_SIZE = _env_int("MYSQL_BATCH_SIZE", 100, min_value=1)
MYSQL_FAIL_ON_ERROR = _env_bool("MYSQL_FAIL_ON_ERROR", True)
MYSQL_DEAD_LETTER_DIR = os.getenv("MYSQL_DEAD_LETTER_DIR", str(ROOT / "run_reports" / "mysql_dead_letters"))
MYSQL_DEAD_LETTER_INCLUDE_ROWS = _env_bool("MYSQL_DEAD_LETTER_INCLUDE_ROWS", False)
MYSQL_MAX_FAILED_BATCHES = _env_int("MYSQL_MAX_FAILED_BATCHES", 20, min_value=0)
MYSQL_RETRY_TIMES = _env_int("MYSQL_RETRY_TIMES", 0, min_value=0)
MYSQL_RETRY_BACKOFF_SECONDS = float(os.getenv("MYSQL_RETRY_BACKOFF_SECONDS", "1.0"))

PG_ENABLED = _env_bool("PG_ENABLED", False)
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = _env_int("PG_PORT", 5432, min_value=1)
PG_DATABASE = os.getenv("PG_DATABASE", "pipesight")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_TABLE = os.getenv("PG_TABLE", "news_articles")
PG_CONNECT_TIMEOUT = _env_int("PG_CONNECT_TIMEOUT", 10, min_value=1)
PG_BATCH_SIZE = _env_int("PG_BATCH_SIZE", 100, min_value=1)
PG_FAIL_ON_ERROR = _env_bool("PG_FAIL_ON_ERROR", True)
PG_DEAD_LETTER_DIR = os.getenv("PG_DEAD_LETTER_DIR", str(ROOT / "run_reports" / "pg_dead_letters"))
PG_DEAD_LETTER_INCLUDE_ROWS = _env_bool("PG_DEAD_LETTER_INCLUDE_ROWS", False)
PG_MAX_FAILED_BATCHES = _env_int("PG_MAX_FAILED_BATCHES", 20, min_value=0)
PG_RETRY_TIMES = _env_int("PG_RETRY_TIMES", 0, min_value=0)
PG_RETRY_BACKOFF_SECONDS = float(os.getenv("PG_RETRY_BACKOFF_SECONDS", "1.0"))

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "news_pipeline")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "news-pipelines-rss-consumer")
KAFKA_AUTO_OFFSET_RESET = os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest")
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "")
KAFKA_SASL_MECHANISM = os.getenv("KAFKA_SASL_MECHANISM", "")
KAFKA_SASL_USERNAME = os.getenv("KAFKA_SASL_USERNAME", "")
KAFKA_SASL_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD", "")
KAFKA_COMMIT_INTERVAL_MSGS = _env_int("KAFKA_COMMIT_INTERVAL_MSGS", 100, min_value=1)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)sZ %(levelname)s [%(name)s] %(message)s"
LOG_DATEFORMAT = "%Y-%m-%dT%H:%M:%S"

FEED_EXPORT_ENCODING = "utf-8"
FEED_EXPORT_INDENT = 2
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
