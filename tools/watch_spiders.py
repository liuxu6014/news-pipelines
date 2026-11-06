"""监听 spider 相关文件变更，并自动重新执行命令。"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def iter_watch_paths(root):
    root = Path(root)
    paths = [root / "run_spider.py", root / ".env", root / ".env.example"]
    paths.extend(root.glob("app/**/*.py"))
    paths.extend(root.glob("tools/**/*.py"))
    for path in paths:
        if path.exists():
            yield path


def snapshot(paths):
    state = {}
    for path in paths:
        try:
            state[str(path)] = path.stat().st_mtime_ns
        except OSError:
            state[str(path)] = 0
    return state


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--command", nargs=argparse.REMAINDER, default=[sys.executable, "run_spider.py", "--dry-run"])
    args = parser.parse_args(argv)
    root = Path(args.root)
    paths = list(iter_watch_paths(root))
    last = snapshot(paths)
    print("Watching", len(paths), "paths")
    while True:
        current = snapshot(paths)
        if current != last:
            last = current
            subprocess.run(args.command, cwd=root, check=False)
        time.sleep(max(args.interval, 0.2))


if __name__ == "__main__":
    raise SystemExit(main())
