"""根据当前项目已加载的 spider 生成 SPIDER_CONFIGS 配置候选。"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_spider

MANUAL_RUNTIME_FIELDS = ("jobdir", "settings", "timeout_seconds")


def build_spider_configs(root=None, include_example=False, existing_entries=None):
    _ = include_example  # 兼容旧签名；迁移前该参数不影响输出，始终包含 example。
    from app.runtime.spider_configs import discover_spider_configs

    # 权威发现逻辑唯一来源：app/runtime/spider_configs.discover_spider_configs()。
    generated = discover_spider_configs(root=root or ROOT, include_example=True)
    existing_by_spider = {
        _entry_spider(entry): entry
        for entry in existing_entries or []
        if _entry_spider(entry)
    }
    entries = [
        merge_spider_config_entry(entry, existing_by_spider.get(_entry_spider(entry)))
        for entry in generated
    ]
    entries.sort(key=lambda entry: entry["spider"])
    return entries


def _entry_spider(entry):
    return str((entry or {}).get("spider") or (entry or {}).get("name") or "").strip()


def merge_spider_config_entry(generated_entry, existing_entry=None):
    if not existing_entry:
        return dict(generated_entry)
    merged = dict(existing_entry)
    merged.update(generated_entry)
    for field in MANUAL_RUNTIME_FIELDS:
        if field in existing_entry:
            merged[field] = existing_entry[field]
    return merged


def merge_spider_config_entries(generated_entries, existing_entries=None):
    existing_by_spider = {
        _entry_spider(entry): entry
        for entry in existing_entries or []
        if _entry_spider(entry)
    }
    return [
        merge_spider_config_entry(entry, existing_by_spider.get(_entry_spider(entry)))
        for entry in generated_entries
    ]


def load_existing_spider_configs(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"spider configs must be a list: {path}")
    return data


def write_spider_configs(output_path, entries):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成可粘贴到 run_spider.py SPIDER_CONFIGS 的配置候选。")
    parser.add_argument("--output", help="Optional output path. Omit to print JSON to stdout.")
    parser.add_argument("--include-example", action="store_true", help="保留兼容参数，当前不会影响输出。")
    args = parser.parse_args(argv)
    existing_entries = run_spider.get_spider_configs()
    entries = build_spider_configs(root=ROOT, include_example=args.include_example, existing_entries=existing_entries)
    if args.output:
        output = write_spider_configs(args.output, entries)
        print(f"wrote {len(entries)} spider config entries to {output}")
    else:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
