"""示例爬虫。

运行：
    uv run scrapy crawl example
    uv run scrapy crawl example -O output.json   # 导出结果到文件
"""

from datetime import UTC, datetime

import scrapy

from app.items import ScrapyTemplateItem


class ExampleSpider(scrapy.Spider):
    # 爬虫的唯一名称，crawl 命令通过它定位爬虫
    name = "example"

    # 允许抓取的域名（可选，用于过滤站外链接）
    allowed_domains = ["quotes.toscrape.com"]

    # 起始 URL 列表
    start_urls = ["https://quotes.toscrape.com/"]

    def parse(self, response):
        """解析响应，产出 Item，并跟进分页链接。"""
        for quote in response.css("div.quote"):
            item = ScrapyTemplateItem()
            item["title"] = quote.css("span.text::text").get()
            item["url"] = response.url
            item["crawled_at"] = datetime.now(UTC).isoformat()
            yield item

        # 跟进“下一页”
        next_page = response.css("li.next a::attr(href)").get()
        if next_page is not None:
            yield response.follow(next_page, callback=self.parse)
