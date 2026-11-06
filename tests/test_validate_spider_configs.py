import unittest
from unittest import mock

from app.runtime.spider_configs import project_root
from tools.validate_spider_configs import validate_spider_configs


class ValidateSpiderConfigsTests(unittest.TestCase):
    def test_project_root_points_to_repository_root(self):
        self.assertTrue((project_root() / "run_spider.py").exists())

    def test_validate_spider_configs_accepts_configured_run_names(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"},
            {"name": "beta", "spider": "beta", "jobdir": "run_state/beta"},
        ]

        with (
            mock.patch("run_spider.get_spider_configs", return_value=entries),
            mock.patch("run_spider.get_spider_run_names", return_value=["beta"]),
        ):
            errors = validate_spider_configs(check_available=False)

        self.assertEqual([], errors)

    def test_validate_spider_configs_rejects_unknown_run_name(self):
        entries = [{"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"}]

        with (
            mock.patch("run_spider.get_spider_configs", return_value=entries),
            mock.patch("run_spider.get_spider_run_names", return_value=["missing"]),
        ):
            errors = validate_spider_configs(check_available=False)

        self.assertIn("run_name_not_configured: missing", errors)

    def test_validate_spider_configs_rejects_entry_without_name(self):
        entries = [{"spider": "alpha", "jobdir": "run_state/alpha"}]

        with (
            mock.patch("run_spider.get_spider_configs", return_value=entries),
            mock.patch("run_spider.get_spider_run_names", return_value=["alpha"]),
        ):
            errors = validate_spider_configs(check_available=False)

        self.assertIn("missing_name: index=0", errors)
        self.assertIn("run_name_not_configured: alpha", errors)

    def test_validate_spider_configs_rejects_entry_without_spider(self):
        entries = [{"name": "alpha", "jobdir": "run_state/alpha"}]

        with (
            mock.patch("run_spider.get_spider_configs", return_value=entries),
            mock.patch("run_spider.get_spider_run_names", return_value=["alpha"]),
        ):
            errors = validate_spider_configs(check_available=False)

        self.assertIn("missing_spider: index=0", errors)

    def test_validate_spider_configs_rejects_duplicate_config_name(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"},
            {"name": "alpha", "spider": "beta", "jobdir": "run_state/beta"},
        ]

        with (
            mock.patch("run_spider.get_spider_configs", return_value=entries),
            mock.patch("run_spider.get_spider_run_names", return_value=["alpha"]),
        ):
            errors = validate_spider_configs(check_available=False)

        self.assertIn("duplicate_name: alpha", errors)

    def test_validate_spider_configs_rejects_duplicate_run_name(self):
        entries = [{"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"}]

        with (
            mock.patch("run_spider.get_spider_configs", return_value=entries),
            mock.patch("run_spider.get_spider_run_names", return_value=["alpha", "alpha"]),
        ):
            errors = validate_spider_configs(check_available=False)

        self.assertIn("duplicate_run_name: alpha", errors)
