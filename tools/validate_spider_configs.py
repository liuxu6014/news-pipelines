"""校验 run_spider.py 中的 SPIDER_RUN_NAMES 和 SPIDER_CONFIGS。"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_spider
from app.runtime.spider_configs import (
    load_available_spiders,
    project_root,
    select_spiders,
    validate_spider_config_entries,
    validate_spider_run_names,
)


def validate_spider_configs(root=None, check_available=False, names=None):
    all_entries = run_spider.get_spider_configs()
    entries = all_entries
    run_names = list(names) if names else run_spider.get_spider_run_names()
    if names:
        entries, _skipped = select_spiders(entries, spider_names=names)
    available = load_available_spiders(root=root) if check_available else None
    errors = validate_spider_config_entries(entries, root=root, available_spiders=available)
    errors.extend(validate_spider_run_names(all_entries, run_names))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(project_root()))
    parser.add_argument("--name", action="append", dest="names", help="Only validate matching configured spider name(s).")
    parser.add_argument("--check-available", action="store_true")
    args = parser.parse_args(argv)
    errors = validate_spider_configs(root=args.root, check_available=args.check_available, names=args.names)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
