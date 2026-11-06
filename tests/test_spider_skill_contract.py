import importlib
import unittest

import scrapy
from scrapy.http import HtmlResponse, Request
from scrapy.spiderloader import SpiderLoader
from scrapy.utils.project import get_project_settings

from app.pipelines import ScrapyTemplatePipeline
from app.runtime.spider_quality import (
    build_quality_report,
    has_mojibake,
    normalize_publish_time,
)
from app.spiders.source_availability import BLOCKED_SOURCES, blocked_source_rows


def _load_template_spider():
    module = importlib.import_module("app.spiders.120_zgznh_com")
    return module.XPathZgznhComSpider


class SpiderSkillContractTests(unittest.TestCase):
    def test_flat_spiders_are_standalone_scrapy_spiders(self):
        loader = SpiderLoader.from_settings(get_project_settings())
        names = [name for name in loader.list() if name != "example"]
        self.assertGreaterEqual(len(names), 100)
        for name in names:
            with self.subTest(spider=name):
                cls = loader.load(name)
                self.assertTrue(issubclass(cls, scrapy.Spider), "必须继承 scrapy.Spider")
                # 禁止项目级通用基类：MRO 中除 scrapy.Spider 外不允许出现 app.* 基类。
                app_bases = [
                    base for base in cls.__mro__[1:] if base.__module__.startswith("app.")
                ]
                self.assertEqual([], app_bases, "禁止继承项目级通用基类")
                self.assertEqual(name, getattr(cls, "name", None))

    def test_flat_spiders_expose_core_metadata(self):
        loader = SpiderLoader.from_settings(get_project_settings())
        required = {
            "site_id",
            "site_name",
            "site_type",
            "language",
            "entry_url",
            "source_title",
            "source_name",
            "source_category",
            "source_site",
            "allowed_domains",
            "section_urls",
            "start_urls",
        }
        for name in loader.list():
            if name == "example":
                continue
            with self.subTest(spider=name):
                cls = loader.load(name)
                self.assertTrue(required.issubset(set(dir(cls))))

    def test_flat_spiders_do_not_define_dead_start_requests(self):
        # Scrapy 2.13+ 的真实入口是 async def start()；同步 start_requests 已不被引擎调用，属死代码。
        # 迁移后所有扁平 spider 都不应再定义它。
        loader = SpiderLoader.from_settings(get_project_settings())
        for name in loader.list():
            if name == "example":
                continue
            with self.subTest(spider=name):
                cls = loader.load(name)
                self.assertNotIn(
                    "start_requests",
                    cls.__dict__,
                    "start_requests 是 Scrapy 2.13+ 的死代码，入口应为 async def start()",
                )

    def test_flat_xpath_spider_extracts_dc_date_and_non_span_time(self):
        # gdbh 把发布时间放在 <meta name="dc.date">，zgznh 放在 <i class="ui-ico-time">，
        # 旧版 DEFAULT_DATE_XPATH 只认 article:published_time / <time> / <span class=time>，
        # 导致空 publish_time。迁移后 DEFAULT_DATE_XPATH 必须覆盖这些来源。
        spider = _load_template_spider()()

        dc_date = HtmlResponse(
            url="https://www.zgznh.com/news/show-1.html",
            body=b'<html><head><meta name="dc.date" content="2026-08-25" /></head><body><p>x</p></body></html>',
            encoding="utf-8",
            request=Request("https://www.zgznh.com/news/show-1.html"),
        )
        self.assertEqual("2026-08-25 00:00:00", spider._extract_date(dc_date))

        icon_time = HtmlResponse(
            url="https://www.zgznh.com/news/show-2.html",
            body=b'<html><body><i class="ui-ico-time">2025-08-28</i></body></html>',
            encoding="utf-8",
            request=Request("https://www.zgznh.com/news/show-2.html"),
        )
        self.assertEqual("2025-08-28 00:00:00", spider._extract_date(icon_time))

        publish_div = HtmlResponse(
            url="https://www.zgznh.com/news/show-3.html",
            body=b'<html><body><div class="publish-time">2026-01-15 10:30</div></body></html>',
            encoding="utf-8",
            request=Request("https://www.zgznh.com/news/show-3.html"),
        )
        self.assertEqual("2026-01-15 10:30:00", spider._extract_date(publish_div))

    def test_publish_time_is_normalized_and_future_dates_are_rejected(self):
        self.assertEqual(
            "2026-06-26 10:30",
            normalize_publish_time(
                "2026-06-26T10:30:00+08:00",
                reference_time="2026-10-22 09:00",
            ),
        )
        self.assertEqual(
            "2026-06-26 10:30",
            normalize_publish_time(
                "2026-06-26T02:30:00Z",
                reference_time="2026-10-22 09:00",
            ),
        )
        self.assertEqual(
            "",
            normalize_publish_time(
                "2027-01-01",
                reference_time="2026-10-22 09:00",
            ),
        )
        self.assertEqual(
            "2026-06-26 00:00",
            normalize_publish_time(
                "https://www.example.gov.cn/202606/t20260626_1.html",
                reference_time="2026-10-22 09:00",
            ),
        )

    def test_common_pipeline_fills_skill_fields_for_specialized_spiders(self):
        pipeline = ScrapyTemplatePipeline()
        item = pipeline.process_item(
            {
                "title": "Specialized source article",
                "url": "https://example.com/news/story?utm_source=test",
                "content": "A complete article body that is long enough for the contract.",
                "publish_time": "2026-07-30T07:30:25+02:00",
                "site_name": "Example source",
                "category": "industry",
            }
        )
        self.assertEqual("https://example.com/news/story", item["canonical_url"])
        self.assertEqual("2026-07-30 13:30", item["publish_time"])
        self.assertEqual("2026-07-30T07:30:25+02:00", item["raw_publish_time"])
        self.assertEqual("Example source", item["source_site"])
        self.assertEqual("industry", item["source_category"])
        self.assertTrue(item["content_preview"])
        self.assertRegex(item["crawled_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_pipeline_preserves_normalized_time_when_raw_text_is_not_machine_parseable(self):
        pipeline = ScrapyTemplatePipeline()
        item = pipeline.process_item(
            {
                "title": "Pipeline time normalization",
                "url": "https://example.com/news/time",
                "content": "A complete article body that is long enough for the contract.",
                "publish_time": "2026-09-21 00:00",
                "raw_publish_time": "September 21",
                "site_name": "Example source",
                "category": "industry",
            }
        )

        self.assertEqual("2026-09-21 00:00", item["publish_time"])
        self.assertEqual("September 21", item["raw_publish_time"])

    def test_mojibake_is_detected(self):
        self.assertTrue(has_mojibake("鍥藉閲戣瀺鐩戠潱绠＄悊鎬诲眬"))
        self.assertFalse(has_mojibake("国家金融监督管理总局"))

    def test_mojibake_does_not_flag_legitimate_rare_chars(self):
        self.assertFalse(has_mojibake("国家金融监督管理总局对王某楠作出处罚"))
        self.assertFalse(has_mojibake("娴熟的缂丝技艺与浠水地名"))
        self.assertFalse(has_mojibake("纨绔子弟与婆娑树影"))

    def test_empty_crawl_does_not_report_schema_pass(self):
        report = build_quality_report(
            [],
            [{"source": "unavailable", "site": "https://example.com/", "visited_pages": 1, "items": 0}],
            pagination_type="discovered_links",
            max_pages=1,
            stop_condition="no_records",
        )
        self.assertEqual("skipped", report["schema_contract"]["status"])
        self.assertEqual("skipped", report["field_quality"]["status"])
        self.assertEqual("skipped", report["encoding_quality"]["status"])

    def test_blocked_sources_are_still_recorded_for_audit(self):
        self.assertIn("江苏省国有资产监督管理委员会", BLOCKED_SOURCES)
        self.assertIn("海南省国有资产监督管理委员会", BLOCKED_SOURCES)
        self.assertIn("公安部", BLOCKED_SOURCES)
        self.assertTrue(all(row["reason"] for row in blocked_source_rows()))


if __name__ == "__main__":
    unittest.main()
