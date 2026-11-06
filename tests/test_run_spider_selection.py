import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import run_spider
from app.runtime.runner import (
    NO_SPIDERS_SELECTED_EXIT_CODE,
    SPIDER_TIMEOUT_EXIT_CODE,
    RunSummary,
    build_crawl_command,
    read_spider_finish_reason,
    run_selected,
)
from app.runtime.spider_configs import select_spiders


class RunSpiderSelectionTests(unittest.TestCase):
    def test_closespider_timeout_is_not_recorded_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = RunSummary(directory, run_id="timeout_check")
            record = summary.record_spider(
                spider="alpha",
                started_at="2026-10-22T00:00:00Z",
                finished_at="2026-10-22T00:01:00Z",
                duration_seconds=60,
                exit_code=0,
                items=1,
                failure_reason="closespider_timeout",
            )
        self.assertEqual("failed", record["status"])
        self.assertEqual("closespider_timeout", record["failure_reason"])

    def test_finish_reason_reader_accepts_js_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text('window.NEWS_DATA = {"reason": "finished"};', encoding="utf-8")
            self.assertEqual("finished", read_spider_finish_reason(report))

    def test_select_spiders_filters_by_name_and_skip(self):
        entries = [
            {"spider": "alpha", "title": "Alpha Water"},
            {"spider": "beta", "title": "Beta Water"},
            {"spider": "gamma", "title": "Gamma News"},
        ]

        selected, skipped = select_spiders(
            entries,
            spider_names=["Water"],
            skip_names=["beta"],
        )

        self.assertEqual(["alpha"], [entry["spider"] for entry in selected])
        self.assertEqual(2, len(skipped))

    def test_build_crawl_command_puts_jobdir_before_other_settings(self):
        command = build_crawl_command(
            "example",
            {"jobdir": "run_state/example", "settings": {"DOWNLOAD_DELAY": "1"}},
            setting_overrides=["RETRY_TIMES=2"],
        )

        self.assertEqual(command[:4], [sys.executable, "-m", "scrapy", "crawl"])
        self.assertIn("-s", command)
        self.assertIn("JOBDIR=run_state/example", command)
        self.assertIn("DOWNLOAD_DELAY=1", command)
        self.assertIn("RETRY_TIMES=2", command)

    def test_build_crawl_command_rejects_sensitive_setting_overrides(self):
        with self.assertRaisesRegex(ValueError, "Sensitive Scrapy setting"):
            build_crawl_command("example", setting_overrides=["MYSQL_PASSWORD=secret"])

    def test_build_crawl_command_rejects_sensitive_config_settings(self):
        with self.assertRaisesRegex(ValueError, "Sensitive Scrapy setting"):
            build_crawl_command("example", {"settings": {"API_TOKEN": "secret"}})

    def test_spider_configs_are_named_list(self):
        names = [entry["name"] for entry in run_spider.SPIDER_CONFIGS]

        self.assertEqual(len(names), len(set(names)))
        self.assertIn("example", names)
        for entry in run_spider.SPIDER_CONFIGS:
            self.assertIn("name", entry)
            self.assertIn("start_urls", entry)
            self.assertIn("jobdir", entry)

    def test_spider_run_names_select_configured_spiders(self):
        config_names = {entry["name"] for entry in run_spider.SPIDER_CONFIGS}

        # 全量迁移后，默认运行清单是全部扁平站点 spider（example 除外）。
        self.assertGreaterEqual(len(run_spider.SPIDER_RUN_NAMES), 100)
        self.assertNotIn("example", run_spider.SPIDER_RUN_NAMES)
        self.assertEqual(len(run_spider.SPIDER_RUN_NAMES), len(set(run_spider.SPIDER_RUN_NAMES)))
        for name in run_spider.SPIDER_RUN_NAMES:
            self.assertIn(name, config_names)

    def test_main_dry_run_uses_in_code_spider_configs(self):
        with mock.patch.object(run_spider, "get_spider_configs", return_value=run_spider.SPIDER_CONFIGS) as configured:
            exit_code = run_spider.main(["--dry-run"])

        self.assertEqual(0, exit_code)
        configured.assert_called_once_with()

    def test_main_dry_run_returns_no_spiders_exit_code_when_selection_is_empty(self):
        entries = [{"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"}]

        with (
            mock.patch.object(run_spider, "get_spider_configs", return_value=entries),
            mock.patch.object(run_spider, "get_spider_run_names", return_value=["missing"]),
        ):
            exit_code = run_spider.main(["--dry-run"])

        self.assertEqual(NO_SPIDERS_SELECTED_EXIT_CODE, exit_code)

    def test_parser_rejects_negative_limit_and_offset(self):
        parser = run_spider.build_parser()
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--limit", "-1"])
            with self.assertRaises(SystemExit):
                parser.parse_args(["--offset", "-1"])

    def test_main_uses_configured_run_names_when_cli_spider_is_omitted(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"},
            {"name": "beta", "spider": "beta", "jobdir": "run_state/beta"},
        ]

        with (
            mock.patch.object(run_spider, "get_spider_configs", return_value=entries),
            mock.patch.object(run_spider, "get_spider_run_names", return_value=["beta"]),
            mock.patch.object(run_spider, "run_selected", return_value=0) as runner,
        ):
            exit_code = run_spider.main([])

        self.assertEqual(0, exit_code)
        selected = runner.call_args.args[0]
        self.assertEqual(["beta"], [entry["name"] for entry in selected])

    def test_configured_run_names_match_name_exactly(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "title": "Beta Water", "jobdir": "run_state/alpha"},
            {"name": "beta", "spider": "beta", "title": "Real Beta", "jobdir": "run_state/beta"},
        ]

        with (
            mock.patch.object(run_spider, "get_spider_configs", return_value=entries),
            mock.patch.object(run_spider, "get_spider_run_names", return_value=["Water"]),
            mock.patch.object(run_spider, "run_selected", return_value=NO_SPIDERS_SELECTED_EXIT_CODE) as runner,
        ):
            exit_code = run_spider.main([])

        self.assertEqual(NO_SPIDERS_SELECTED_EXIT_CODE, exit_code)
        selected = runner.call_args.args[0]
        self.assertEqual([], selected)

    def test_empty_configured_run_names_selects_no_spiders(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"},
            {"name": "beta", "spider": "beta", "jobdir": "run_state/beta"},
        ]

        with (
            mock.patch.object(run_spider, "get_spider_configs", return_value=entries),
            mock.patch.object(run_spider, "get_spider_run_names", return_value=[]),
            mock.patch.object(run_spider, "run_selected", return_value=NO_SPIDERS_SELECTED_EXIT_CODE) as runner,
        ):
            exit_code = run_spider.main([])

        self.assertEqual(NO_SPIDERS_SELECTED_EXIT_CODE, exit_code)
        selected = runner.call_args.args[0]
        self.assertEqual([], selected)

    def test_cli_spider_overrides_configured_run_names(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"},
            {"name": "beta", "spider": "beta", "jobdir": "run_state/beta"},
        ]

        with (
            mock.patch.object(run_spider, "get_spider_configs", return_value=entries),
            mock.patch.object(run_spider, "get_spider_run_names", return_value=["beta"]),
            mock.patch.object(run_spider, "run_selected", return_value=0) as runner,
        ):
            exit_code = run_spider.main(["--spider", "alpha"])

        self.assertEqual(0, exit_code)
        selected = runner.call_args.args[0]
        self.assertEqual(["alpha"], [entry["name"] for entry in selected])

    def test_cli_spider_override_matches_name_exactly(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "title": "Water spider", "jobdir": "run_state/alpha"},
            {"name": "beta", "spider": "beta", "title": "Other spider", "jobdir": "run_state/beta"},
        ]

        with (
            mock.patch.object(run_spider, "get_spider_configs", return_value=entries),
            mock.patch.object(run_spider, "get_spider_run_names", return_value=["beta"]),
            mock.patch.object(run_spider, "run_selected", return_value=NO_SPIDERS_SELECTED_EXIT_CODE) as runner,
        ):
            exit_code = run_spider.main(["--spider", "Water"])

        self.assertEqual(NO_SPIDERS_SELECTED_EXIT_CODE, exit_code)
        selected = runner.call_args.args[0]
        self.assertEqual([], selected)

    def test_run_selected_times_out_and_records_timeout_exit_code(self):
        class FakeProcess:
            def __init__(self):
                self.stdout = io.StringIO("starting crawl\n")
                self.killed = False
                self.wait_calls = []

            def wait(self, timeout=None):
                self.wait_calls.append(timeout)
                if timeout is not None and not self.killed:
                    raise subprocess.TimeoutExpired(cmd="scrapy crawl example", timeout=timeout)
                return 0

            def kill(self):
                self.killed = True

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_process = FakeProcess()
            summary_dir = Path(tmpdir) / "summary"
            args = SimpleNamespace(
                output_dir=None,
                summary_dir=str(summary_dir),
                run_id="run-1",
                root=tmpdir,
                fresh=False,
                setting=[],
                stop_on_failure=False,
                allow_empty=False,
            )
            selected = [
                {
                    "name": "example",
                    "spider": "example",
                    "jobdir": "run_state/example",
                    "timeout_seconds": 0.01,
                }
            ]

            with mock.patch("app.runtime.runner.subprocess.Popen", return_value=fake_process):
                exit_code = run_selected(selected, args, logger=mock.Mock())

            self.assertEqual(1, exit_code)
            self.assertTrue(fake_process.killed)
            self.assertGreaterEqual(len(fake_process.wait_calls), 1)
            self.assertEqual(0.01, fake_process.wait_calls[0])

            spider_summary = json.loads((summary_dir / "run-1" / "spiders" / "example.json").read_text(encoding="utf-8"))
            self.assertEqual(SPIDER_TIMEOUT_EXIT_CODE, spider_summary["exit_code"])

    def test_external_config_argument_is_not_exposed(self):
        help_output = io.StringIO()
        legacy_arg = "--" + "manifest"

        with self.assertRaises(SystemExit), redirect_stdout(help_output):
            run_spider.build_parser().parse_args(["--help"])

        self.assertNotIn(legacy_arg, help_output.getvalue())

    def test_command_examples_are_not_exposed_from_runtime_entry(self):
        output = io.StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit):
            run_spider.build_parser().parse_args(["--help"])

        self.assertFalse(hasattr(run_spider, "RUN_EXAMPLES"))
        self.assertNotIn("--examples", output.getvalue())
        self.assertNotIn("--example", output.getvalue())

    def test_build_spider_configs_active_json_argument_is_not_exposed(self):
        import tools.build_spider_configs as build_spider_configs

        output = io.StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit):
            build_spider_configs.main(["--help"])

        self.assertNotIn("--active-output", output.getvalue())
