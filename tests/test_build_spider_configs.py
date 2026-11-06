import json
import tempfile
import unittest
from pathlib import Path

from tools.build_spider_configs import merge_spider_config_entries, write_spider_configs


class BuildSpiderConfigsTests(unittest.TestCase):
    def test_merge_spider_config_entries_preserves_manual_runtime_fields(self):
        generated = [
            {
                "spider": "example",
                "name": "example",
                "title": "example from code",
                "start_urls": ["https://new.example/"],
                "jobdir": "run_state/example",
                "settings": {},
            }
        ]
        existing = [
            {
                "spider": "example",
                "name": "example",
                "title": "old title",
                "start_urls": ["https://old.example/"],
                "jobdir": "run_state/custom-example",
                "settings": {"DOWNLOAD_DELAY": "2"},
                "owner": "water-team",
            }
        ]

        merged = merge_spider_config_entries(generated, existing)

        self.assertEqual("example from code", merged[0]["title"])
        self.assertEqual(["https://new.example/"], merged[0]["start_urls"])
        self.assertEqual("run_state/custom-example", merged[0]["jobdir"])
        self.assertEqual({"DOWNLOAD_DELAY": "2"}, merged[0]["settings"])
        self.assertEqual("water-team", merged[0]["owner"])

    def test_merge_spider_config_entries_keeps_new_spiders(self):
        generated = [{"spider": "new_site", "name": "new_site", "jobdir": "run_state/new_site", "settings": {}}]

        merged = merge_spider_config_entries(generated, [])

        self.assertEqual(generated, merged)

    def test_write_spider_configs_writes_preview_json(self):
        entries = [
            {"name": "alpha", "spider": "alpha", "jobdir": "run_state/alpha"},
            {"name": "beta", "spider": "beta", "jobdir": "run_state/beta"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nested" / "preview.json"
            output = write_spider_configs(output_path, entries)

            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(output_path, output)
        self.assertEqual(entries, data)
