"""Runner primitives for executing configured spiders."""

import contextlib
import json
import logging
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread

from app.runtime.spider_configs import entry_spider, project_root

LOGGER_NAME = "app.runtime.runner"
NO_SPIDERS_SELECTED_EXIT_CODE = 66
SPIDER_TIMEOUT_EXIT_CODE = 124
SENSITIVE_SETTING_RE = re.compile(
    r"(password|passwd|pwd|secret|token|credential|api[_-]?key|access[_-]?key|private[_-]?key)",
    re.I,
)


def utc_now_iso():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_run_id():
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _setting_key(setting):
    key, _separator, _value = str(setting or "").partition("=")
    return key.strip()


def _ensure_runtime_setting_allowed(setting, source):
    key = _setting_key(setting)
    if not key:
        raise ValueError(f"Invalid empty Scrapy setting from {source}.")
    if SENSITIVE_SETTING_RE.search(key):
        raise ValueError(
            f"Sensitive Scrapy setting {key!r} must be supplied through .env or process environment, "
            f"not {source}."
        )
    return key


def _normalize_timeout_seconds(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid spider timeout value: {value!r}") from exc
    return timeout_seconds if timeout_seconds > 0 else None


def _start_output_reader(process, logger, spider):
    if not process.stdout:
        return None

    def _read_output():
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                logger.info("SPIDER_LOG spider=%s %s", spider, line.rstrip())
        finally:
            with contextlib.suppress(Exception):
                process.stdout.close()

    thread = Thread(target=_read_output, name=f"spider-log-{spider}", daemon=True)
    thread.start()
    return thread


def _wait_for_process(process, logger, spider, timeout_seconds=None):
    reader = _start_output_reader(process, logger, spider)
    timed_out = False
    try:
        return_code = process.wait() if timeout_seconds is None else process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        logger.error("SPIDER_TIMEOUT spider=%s timeout_s=%s", spider, timeout_seconds)
        process.kill()
        with contextlib.suppress(Exception):
            process.wait(timeout=5)
        return_code = SPIDER_TIMEOUT_EXIT_CODE
    finally:
        if reader:
            reader.join(timeout=5)
    return return_code, timed_out


class RunSummary:
    def __init__(self, root_dir, run_id=None, spiders_total=0):
        self.root_dir = Path(root_dir)
        self.run_id = run_id or generate_run_id()
        self.run_dir = self.root_dir / self.run_id
        self.spiders_dir = self.run_dir / "spiders"
        self.started_at = utc_now_iso()
        self.finished_at = None
        self.spiders_total = int(spiders_total or 0)
        self.records = []
        self.spiders_dir.mkdir(parents=True, exist_ok=True)

    def record_spider(self, spider, started_at, finished_at, duration_seconds, exit_code, items=0, failure_reason=""):
        status = "success" if int(exit_code) == 0 and not failure_reason else "failed"
        record = {
            "run_id": self.run_id,
            "spider": spider,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "exit_code": int(exit_code),
            "status": status,
            "items": int(items or 0),
            "failure_reason": failure_reason or ("" if status == "success" else f"exit_{exit_code}"),
        }
        self.records.append(record)
        self._write_json(self.spiders_dir / f"{spider}.json", record)
        return record

    def finish(self):
        self.finished_at = utc_now_iso()
        summary = self._summary()
        self._write_json(self.run_dir / "summary.json", summary)
        return summary

    def _summary(self):
        successes = [record for record in self.records if record["status"] == "success"]
        failures = [record for record in self.records if record["status"] != "success"]
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": "failed" if failures else "success",
            "spiders_total": self.spiders_total,
            "spiders_finished": len(self.records),
            "spiders_success": len(successes),
            "spiders_failed": len(failures),
            "items": sum(record["items"] for record in self.records),
            "failed_spiders": [record["spider"] for record in failures],
        }

    @staticmethod
    def _write_json(path, data):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class SpiderRunTimer:
    def __init__(self):
        self.started_at = utc_now_iso()
        self.monotonic = time.monotonic()

    def finish(self):
        return utc_now_iso(), round(time.monotonic() - self.monotonic, 3)


def configure_logging(log_file=None, stream=None, level=logging.INFO):
    configure_output_streams()
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger


def configure_output_streams():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def build_crawl_command(spider_name, spider_config=None, output_file=None, setting_overrides=None):
    spider_config = dict(spider_config or {})
    command = [sys.executable, "-m", "scrapy", "crawl", spider_name]
    settings = {}

    jobdir = spider_config.get("jobdir")
    if jobdir:
        settings["JOBDIR"] = str(jobdir)
    for key, value in (spider_config.get("settings") or {}).items():
        setting_key = _ensure_runtime_setting_allowed(key, "SPIDER_CONFIGS settings")
        settings[setting_key] = str(value)
    for setting in setting_overrides or []:
        key, separator, value = str(setting).partition("=")
        key = _ensure_runtime_setting_allowed(key, "--setting")
        if separator:
            settings[key] = value
        else:
            settings[key] = "1"

    if "JOBDIR" in settings:
        command.extend(["-s", f"JOBDIR={settings.pop('JOBDIR')}"])
    for key in sorted(settings):
        command.extend(["-s", f"{key}={settings[key]}"])
    if output_file:
        command.extend(["-O", str(output_file)])
    return command


def redact_setting(setting):
    key, separator, _value = str(setting or "").partition("=")
    if separator and SENSITIVE_SETTING_RE.search(key):
        return f"{key}=<redacted>"
    return str(setting or "")


def redact_command(command):
    redacted = []
    redact_next = False
    for part in command:
        if redact_next:
            redacted.append(redact_setting(part))
            redact_next = False
            continue
        redacted.append(part)
        if part == "-s":
            redact_next = True
    return redacted


def _spider_name(entry):
    return entry_spider(entry)


def _entry_jobdir(entry):
    if entry.get("jobdir"):
        return str(entry["jobdir"])
    return str(Path("run_state") / _spider_name(entry))


def _entry_config(entry):
    config = dict(entry)
    config["jobdir"] = _entry_jobdir(entry)
    config["settings"] = dict(entry.get("settings") or {})
    return config


def resolve_jobdir_path(jobdir, root=None, state_dir="run_state"):
    root_path = Path(root or project_root()).resolve()
    state_root = (root_path / state_dir).resolve()
    candidate = Path(jobdir)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(state_root)
    except ValueError as exc:
        raise ValueError(f"Unsafe JOBDIR outside {state_root}: {resolved}") from exc
    if resolved == state_root:
        raise ValueError(f"Unsafe JOBDIR points to state root: {resolved}")
    return resolved


def prepare_jobdir(jobdir, fresh=False, root=None, state_dir="run_state"):
    jobdir_path = resolve_jobdir_path(jobdir, root=root, state_dir=state_dir)
    if fresh and jobdir_path.exists():
        if jobdir_path.is_dir():
            shutil.rmtree(jobdir_path)
        else:
            jobdir_path.unlink()
    jobdir_path.mkdir(parents=True, exist_ok=True)
    return jobdir_path


def count_output_items(output_file):
    path = Path(output_file) if output_file else None
    if not path or not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as file:
        return sum(1 for line in file if line.strip())


def read_spider_finish_reason(report_file):
    path = Path(report_file) if report_file else None
    if not path or not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("window."):
        text = re.sub(r"^window\.[A-Z0-9_]+\s*=\s*", "", text).rstrip().rstrip(";")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ""
    return str(payload.get("reason") or "")


def run_selected(selected, args, logger=None):
    logger = logger or configure_logging()
    if not selected and not getattr(args, "allow_empty", False):
        logger.error("No spiders selected")
        return NO_SPIDERS_SELECTED_EXIT_CODE

    output_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    run_summary = None
    summary_dir = getattr(args, "summary_dir", None)
    if summary_dir:
        run_summary = RunSummary(summary_dir, run_id=getattr(args, "run_id", None), spiders_total=len(selected))
        logger.info("RUN_SUMMARY_STARTED run_id=%s dir=%s", run_summary.run_id, run_summary.run_dir)

    failures = []
    root = Path(getattr(args, "root", project_root()))
    fresh_mode = bool(getattr(args, "fresh", False))
    for index, entry in enumerate(selected, start=1):
        spider = _spider_name(entry)
        jobdir_path = resolve_jobdir_path(_entry_jobdir(entry), root=root)
        prepare_jobdir(jobdir_path, fresh=fresh_mode, root=root)
        output_file = output_dir / f"{spider}.jsonl" if output_dir else None
        command = build_crawl_command(spider, _entry_config(entry), output_file=output_file, setting_overrides=args.setting)
        report_file = None
        if run_summary:
            report_file = run_summary.run_dir / "raw" / f"{spider}.json"
            command.extend(["-a", f"output={report_file}"])
        timeout_seconds = _normalize_timeout_seconds(entry.get("timeout_seconds"))
        timer = SpiderRunTimer()
        logger.info("SPIDER_STARTED spider=%s index=%s total=%s", spider, index, len(selected))
        logger.info("[%s/%s] %s", index, len(selected), " ".join(redact_command(command)))
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return_code, timed_out = _wait_for_process(process, logger, spider, timeout_seconds)
        finished_at, duration_s = timer.finish()
        items = count_output_items(output_file)
        finish_reason = read_spider_finish_reason(report_file)
        failure_reason = ""
        if timed_out:
            failure_reason = "timeout"
        elif finish_reason == "closespider_timeout":
            failure_reason = "closespider_timeout"
        if run_summary:
            run_summary.record_spider(
                spider=spider,
                started_at=timer.started_at,
                finished_at=finished_at,
                duration_seconds=duration_s,
                exit_code=return_code,
                items=items,
                failure_reason=failure_reason,
            )
        if return_code != 0 or failure_reason:
            failures.append((spider, return_code))
            logger.error(
                "SPIDER_FAILED spider=%s exit_code=%s duration_s=%s reason=%s",
                spider,
                return_code,
                duration_s,
                failure_reason or f"exit_{return_code}",
            )
            if getattr(args, "stop_on_failure", False):
                break
        else:
            logger.info("SPIDER_FINISHED spider=%s exit_code=0 duration_s=%s", spider, duration_s)

    if run_summary:
        summary = run_summary.finish()
        logger.info("RUN_SUMMARY_FINISHED run_id=%s status=%s", summary["run_id"], summary["status"])
    return 1 if failures else 0
