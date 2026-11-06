"""Generic crawl quality rules for monitor summaries."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityThresholds:
    min_items: int = 0
    max_dropped: int = 0
    max_spider_errors: int = 0
    max_db_errors: int = 0


def evaluate_quality(summary, thresholds=None):
    thresholds = thresholds or QualityThresholds()
    issues = []
    _check(issues, "too_few_items", summary.get("item_scraped_count"), thresholds.min_items, "<")
    _check(issues, "too_many_drops", summary.get("item_dropped_count"), thresholds.max_dropped, ">")
    _check(issues, "spider_errors", summary.get("spider_error_count"), thresholds.max_spider_errors, ">")
    _check(issues, "db_errors", summary.get("db_error_count"), thresholds.max_db_errors, ">")
    return issues


def _check(issues, reason, value, threshold, operator):
    value = _int(value)
    threshold = _int(threshold)
    failed = value < threshold if operator == "<" else value > threshold
    if failed:
        issues.append({"reason": reason, "value": value, "threshold": threshold})


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
