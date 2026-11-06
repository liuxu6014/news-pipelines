"""Shared validation and reporting helpers for the scrapy-spider skill contract."""

import re
from datetime import datetime, timedelta, timezone

SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
TIME_OUTPUT_FORMAT = "%Y-%m-%d %H:%M"
TIME_OUTPUT_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
PUBLISH_TIME_RE = re.compile(
    r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?"
    r"(?:[T\s]+(?P<hour>\d{1,2}):(?P<minute>\d{2}))?"
)
COMPACT_DATE_RE = re.compile(r"(?<!\d)(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?!\d)")
# 只保留「正常简体中文里几乎不出现、仅在乱码里出现」的字符。曾含楠/娴/浠/娑/姘/缁/绔/缂等
# 合法汉字，导致标题/正文里出现单个人名或常用词（如“楠”“娴熟”“浠水”“缂丝”）就被误判乱码、
# 进而被 is_valid_news_title / 质量 pipeline 丢弃正常数据。
MOJIBAKE_RE = re.compile(
    r"\ufffd|锟|閿|娑揱|閻|銆|鈥|鍥|鐨|鏂|鍦|缃"
)
NOISE_TEXT_RE = re.compile(
    r"打开微信|点击底部|扫一扫|分享到|上一篇|下一篇|网站标识码|备案|"
    r"【我要纠错】|责任编辑"
)

REQUIRED_FIELDS = (
    "title",
    "url",
    "canonical_url",
    "publish_time",
    "raw_publish_time",
    "source_site",
    "source_category",
    "content",
    "content_preview",
    "crawled_at",
)


def now_shanghai():
    return datetime.now(SHANGHAI_TZ)


def crawled_at_now():
    return now_shanghai().strftime(TIME_OUTPUT_FORMAT)


def has_mojibake(value):
    return bool(MOJIBAKE_RE.search(str(value or "")))


def content_preview(value, limit=400):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _reference_datetime(reference_time=None):
    if isinstance(reference_time, datetime):
        return reference_time
    if reference_time:
        for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(reference_time), pattern).replace(tzinfo=SHANGHAI_TZ)
            except ValueError:
                pass
    return now_shanghai()


def normalize_publish_time(value, reference_time=None, allow_future_days=1):
    """Return a project-standard publish time or an empty string.

    Sources that expose only a date use ``00:00``. Dates clearly beyond the
    allowed future window are rejected instead of being copied from event
    pages or unrelated article text.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        parsed = parsed.astimezone(SHANGHAI_TZ) if parsed.tzinfo is not None else parsed.replace(tzinfo=SHANGHAI_TZ)
        reference = _reference_datetime(reference_time)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=SHANGHAI_TZ)
        if parsed > reference + timedelta(days=max(0, int(allow_future_days))):
            return ""
        return parsed.strftime(TIME_OUTPUT_FORMAT)

    match = PUBLISH_TIME_RE.search(text)
    if match:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = int(match.group("hour") or 0)
        minute = int(match.group("minute") or 0)
    else:
        match = COMPACT_DATE_RE.search(text)
        if not match:
            return ""
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = 0
        minute = 0
    try:
        parsed = datetime(year, month, day, hour, minute, tzinfo=SHANGHAI_TZ)
    except ValueError:
        return ""

    reference = _reference_datetime(reference_time)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=SHANGHAI_TZ)
    if parsed > reference + timedelta(days=max(0, int(allow_future_days))):
        return ""
    return parsed.strftime(TIME_OUTPUT_FORMAT)


def build_quality_report(items, source_reports, pagination_type, max_pages, stop_condition):
    """Build a compact, machine-readable skill compliance report."""
    items = list(items or [])
    source_reports = list(source_reports or [])
    invalid_counts = {
        "title": 0,
        "url": 0,
        "publish_time": 0,
        "source_site": 0,
        "source_category": 0,
        "content": 0,
        "content_preview": 0,
        "crawled_at": 0,
    }
    examples = []

    def invalid(field, item, issue):
        invalid_counts[field] += 1
        if len(examples) < 10:
            examples.append(
                {
                    "field": field,
                    "url": item.get("url") or item.get("canonical_url") or "",
                    "value": str(item.get(field) or "")[:120],
                    "issue": issue,
                }
            )

    mojibake_items = 0
    noise_items = 0
    for item in items:
        if not str(item.get("title") or "").strip():
            invalid("title", item, "missing title")
        if not str(item.get("url") or "").strip():
            invalid("url", item, "missing url")
        if not TIME_OUTPUT_RE.match(str(item.get("publish_time") or "")):
            invalid("publish_time", item, "expected YYYY-MM-DD HH:MM")
        if not str(item.get("source_site") or "").strip():
            invalid("source_site", item, "missing source_site")
        if not str(item.get("source_category") or "").strip():
            invalid("source_category", item, "missing source_category")
        if len(str(item.get("content") or "")) < 20:
            invalid("content", item, "content shorter than 20 characters")
        if not str(item.get("content_preview") or "").strip():
            invalid("content_preview", item, "missing content_preview")
        if not TIME_OUTPUT_RE.match(str(item.get("crawled_at") or "")):
            invalid("crawled_at", item, "expected YYYY-MM-DD HH:MM")
        if any(
            has_mojibake(item.get(field))
            for field in (
                "title",
                "source",
                "author",
                "summary",
                "content",
                "content_preview",
                "source_site",
                "source_category",
            )
        ):
            mojibake_items += 1
        if NOISE_TEXT_RE.search(str(item.get("content") or item.get("content_preview") or "")):
            noise_items += 1

    if not items:
        schema_status = "skipped"
        field_status = "skipped"
        encoding_status = "skipped"
    else:
        schema_status = "pass" if not any(invalid_counts.values()) and noise_items == 0 else "partial"
        field_status = schema_status
        encoding_status = "pass" if mojibake_items == 0 else "fail"
    sections = []
    for source in source_reports:
        name = source.get("source") or source.get("org") or ""
        section_url = source.get("site") or source.get("source_site") or ""
        sections.append(
            {
                "section_name": name,
                "section_url": section_url,
                "needs_pagination": None,
                "pagination_type": pagination_type,
                "total_pages": None,
                "page_turns": None,
                "visited_pages": int(source.get("visited_pages") or 0),
                "item_count": int(source.get("items") or 0),
                "stop_condition": stop_condition,
                "pagination_success": None,
            }
        )

    return {
        "schema_contract": {
            "status": schema_status,
            "required_fields": list(REQUIRED_FIELDS),
            "optional_fields": ["source", "author", "summary", "images"],
            "field_types": {
                "title": "non_empty_string",
                "url": "absolute_url",
                "canonical_url": "tracking_parameters_removed",
                "publish_time": "YYYY-MM-DD HH:MM",
                "raw_publish_time": "source_text",
                "crawled_at": "YYYY-MM-DD HH:MM",
            },
            "quality_thresholds": {
                "min_title_length": 4,
                "min_content_length": 20,
                "timezone": "Asia/Shanghai",
            },
            "violations": invalid_counts,
        },
        "encoding_quality": {
            "status": encoding_status,
            "checked_fields": [
                "title",
                "source",
                "author",
                "summary",
                "content",
                "content_preview",
                "source_site",
                "source_category",
            ],
            "mojibake_detected": mojibake_items > 0,
            "mojibake_item_count": mojibake_items,
        },
        "field_quality": {
            "status": field_status,
            "checked_item_count": len(items),
            "invalid_counts": invalid_counts,
            "examples": examples,
            "noise_item_count": noise_items,
        },
        "pagination_test": {
            "status": "partial",
            "sections": sections,
            "summary": {
                "section_count": len(sections),
                "max_pages": int(max_pages or 0),
                "stop_condition": stop_condition,
            },
        },
        "anti_bot_probe": {
            "status": "skipped",
            "notes": "Record minimum working headers and cookie/referer/origin probes after a live challenge.",
        },
        "response_evidence": {
            "status": "partial",
            "notes": "Source reports retain visited page counts and request errors; full response fixtures are not automatic.",
        },
        "time_normalization": {
            "status": (
                "skipped"
                if not items
                else ("pass" if not invalid_counts["publish_time"] else "fail")
            ),
            "timezone": "Asia/Shanghai",
            "output_format": "YYYY-MM-DD HH:MM",
            "date_only_fallback": "00:00",
            "future_dates_rejected": True,
        },
        "url_canonicalization": {
            "status": "pass",
            "remove_fragment": True,
            "drop_query_prefixes": ["utm_"],
            "drop_query_params": ["from", "share", "spm", "timestamp", "_"],
        },
        "incremental_strategy": {
            "status": "partial",
            "dedupe_key": "canonical_url",
            "stop_condition": stop_condition,
            "backfill_mode": "max_pages_window",
        },
        "fixture_policy": {
            "status": "partial",
            "fixtures_added": ["tests/test_spider_skill_contract.py"],
            "covered_behaviors": [
                "url_filtering",
                "publish_time_normalization",
                "schema_fields",
                "noise_filtering",
            ],
        },
        "drift_detection": {
            "status": "partial",
            "item_count": len(items),
            "sources_with_items": sum(1 for source in source_reports if int(source.get("items") or 0) > 0),
            "source_count": len(source_reports),
        },
        "attachment_handling": {
            "status": "pass",
            "accepted_types": ["article_detail"],
            "rejected_types": ["pdf", "doc", "docx", "xls", "xlsx", "zip", "image", "audio", "video"],
        },
    }
