"""CLI entry for running project spiders and discovering project commands."""

import argparse
from copy import deepcopy

from app.runtime.runner import (
    NO_SPIDERS_SELECTED_EXIT_CODE,
    configure_logging,
    generate_run_id,
    run_selected,
)
from app.runtime.source_gate import select_enabled
from app.runtime.spider_configs import (
    discover_spider_configs,
    entry_name,
    entry_spider,
    load_available_spiders,
    matches_entry,
    project_root,
)

# SPIDER_CONFIGS is discovered from Scrapy's spider loader rather than
# hand-maintained. It covers every flat per-site spider living directly under
# app/spiders/ (NNN_<host>.py) plus the example spider. The legacy family
# packages (company_news, gov_news, industry_knowledge, pipeline_operators_news)
# have been removed; discovery now reflects the flat per-site convention.
SPIDER_CONFIGS = discover_spider_configs(include_example=True)

# Default run: every configured flat per-site spider, in sorted order.
SPIDER_RUN_NAMES = [
    entry_name(entry)
    for entry in SPIDER_CONFIGS
    if entry_spider(entry) != "example"
]


def get_spider_configs():
    return deepcopy(SPIDER_CONFIGS)


def get_spider_run_names():
    return list(SPIDER_RUN_NAMES)


def format_spider_run_names():
    names = get_spider_run_names()
    if not names:
        return "  <none>"
    return "\n".join(f"  {name}" for name in names)


def select_configured_spiders(entries, run_names, skip_names=None, limit=None, offset=0, available_spiders=None):
    names = [str(name).strip() for name in run_names or [] if str(name).strip()]
    names_set = set(names)
    entries_by_name = {str(entry_name(entry) or "").strip(): entry for entry in entries}
    skipped = [(entry, "not_selected") for entry in entries if str(entry_name(entry) or "").strip() not in names_set]
    available = set(available_spiders or []) if available_spiders is not None else None
    skip_tokens = list(skip_names or [])
    selected = []

    for name in names:
        entry = entries_by_name.get(name)
        if entry is None:
            skipped.append(({"name": name}, "not_configured"))
            continue
        if skip_tokens and matches_entry(entry, skip_tokens):
            skipped.append((entry, "excluded"))
            continue
        if available is not None and entry_spider(entry) not in available:
            skipped.append((entry, "not_available"))
            continue
        selected.append(entry)

    end = offset + limit if limit is not None else None
    return selected[offset:end], skipped


def positive_int(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def non_negative_int(value):
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run Scrapy spiders named in run_spider.py SPIDER_RUN_NAMES.",
        epilog="Configured spider run names:\n" + format_spider_run_names(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--resume", action="store_true", help="Resume from existing Scrapy job state.")
    mode_group.add_argument("--fresh", action="store_true", help="Clear spider job state before crawling.")
    parser.add_argument("--spider", action="append", dest="spider_names", help="Override SPIDER_RUN_NAMES for this run.")
    parser.add_argument("--skip", action="append", dest="skip_names", help="Spider name, title, URL, file path, or glob to skip.")
    parser.add_argument("--limit", type=positive_int)
    parser.add_argument("--offset", type=non_negative_int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--available-only", action="store_true")
    parser.add_argument("--output-dir", default=str(project_root() / "run_reports" / "items"))
    parser.add_argument("--summary-dir", default=str(project_root() / "run_reports"))
    parser.add_argument("--run-id", default=generate_run_id())
    parser.add_argument("--log-file")
    parser.add_argument("--setting", action="append", default=[])
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--allow-empty", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    logger = configure_logging(args.log_file)
    logger.info("RUN_MODE mode=%s", "fresh" if args.fresh else "resume")
    spider_configs = get_spider_configs()
    available = load_available_spiders() if args.available_only else None
    run_names = args.spider_names if args.spider_names is not None else get_spider_run_names()
    selected, skipped = select_configured_spiders(
        spider_configs,
        run_names,
        skip_names=args.skip_names,
        limit=args.limit,
        offset=args.offset,
        available_spiders=available,
    )
    selected, gated_out = select_enabled(selected, logger=logger)
    for entry, reason in gated_out:
        logger.info("SKIP source_gate=%s spider=%s", reason, entry_name(entry))
    logger.info("Selected spiders: %s", len(selected))
    for entry in selected:
        logger.info("RUN %s | %s | %s", entry_spider(entry), entry.get("folder", ""), entry.get("title", ""))
    logger.info("Skipped spiders: %s", len(skipped))
    if gated_out:
        logger.info("Skipped by source gate: %s", len(gated_out))
    if args.dry_run:
        if not selected and not args.allow_empty:
            logger.error("No spiders selected")
            return NO_SPIDERS_SELECTED_EXIT_CODE
        return 0
    return run_selected(selected, args, logger=logger)


if __name__ == "__main__":
    raise SystemExit(main())
