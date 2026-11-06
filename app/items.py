"""Item definitions for the project."""

import scrapy


class ScrapyTemplateItem(scrapy.Item):
    title = scrapy.Field()
    url = scrapy.Field()
    canonical_url = scrapy.Field()
    url_hash = scrapy.Field()
    content_hash = scrapy.Field()
    content = scrapy.Field()
    content_md = scrapy.Field()
    content_preview = scrapy.Field()
    summary = scrapy.Field()
    publish_time = scrapy.Field()
    raw_publish_time = scrapy.Field()
    author = scrapy.Field()
    source = scrapy.Field()
    source_site = scrapy.Field()
    source_category = scrapy.Field()
    domain = scrapy.Field()
    images = scrapy.Field()
    image_url = scrapy.Field()
    raw_item = scrapy.Field()
    crawled_at = scrapy.Field()
