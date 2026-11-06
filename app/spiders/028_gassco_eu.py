"""'Gassco'（'国际管道'）独立爬虫 —— 直连 WordPress REST API，采集全部栏目。

站点：'https://gassco.eu/en/home/'
数据源：'https://gassco.eu/wp-json/wp/v2'（WordPress REST API）

「全部栏目」：逐栏目枚举站点的内容型 post type。每个接口一次返回完整字段
（title / content / excerpt / date / link），无需再抓详情页。接口返回的
``content.rendered`` / ``excerpt.rendered`` 是 HTML，统一用 ``scrapy.Selector`` 的
XPath（``//text()``）提取纯文本。分页依据响应头 ``X-WP-TotalPages``，取不到时以
空列表兜底停止。纯结构化参考数据（设施、产品、联系人等）不算内容栏目，未纳入。

本脚本自包含全部抓取/解析逻辑，仅依赖 scrapy 与 Python 标准库，不继承任何项目级
通用爬虫基类。
"""
import html
import re
from datetime import datetime
from urllib.parse import urlparse

import scrapy
from scrapy import Selector

from app.html_markdown import html_images, html_to_markdown

_API = 'https://gassco.eu/wp-json/wp/v2'
_PER_PAGE = 50

# (WP REST 资源名, 栏目中文名)
_CONTENT_TYPES = (
        ('posts', '新闻'),
        ('projects', '项目'),
    )

_SPACE_RE = re.compile(r"\s+")


def _clean(value):
    return _SPACE_RE.sub(" ", str(value or "").replace("\u00a0", " ")).strip()


def _field(post, name, sub="rendered"):
    """兼容 WP REST 中字段既可能是 dict（{rendered: ...}）也可能是纯字符串。"""
    if not isinstance(post, dict):
        return ""
    value = post.get(name)
    if isinstance(value, dict):
        return value.get(sub) or ""
    return value or ""


def _strip_html(fragment):
    """用 XPath 从 HTML 片段提取纯文本。"""
    if not fragment:
        return ""
    selector = Selector(text=str(fragment))
    parts = selector.xpath(
        "//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)]"
    ).getall()
    return _clean(" ".join(parts))


def _normalize_date(value):
    text = _clean(value)
    if not text:
        return ""
    try:
        # WP REST 的 date 形如 "2026-10-28T15:47:21"（站点本地时间，无时区）。
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


def _int_header(response, name):
    raw = response.headers.get(name)
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    return 0


class GasscoEuSpider(scrapy.Spider):
    name = '028_gassco_eu'
    site_id = 'gassco.eu'
    site_name = 'Gassco'
    site_type = 'pipe'
    language = 'en'
    source_title = 'Gassco'
    source_name = 'Gassco'
    source_category = '国际管道'
    source_site = 'https://gassco.eu/en/home/'
    allowed_domains = ['gassco.eu']
    entry_url = 'https://gassco.eu/en/home/'
    section_urls = ['https://gassco.eu/wp-json/wp/v2/posts', 'https://gassco.eu/wp-json/wp/v2/projects']
    start_urls = ['https://gassco.eu/wp-json/wp/v2/posts?per_page=50&page=1']
    strict_news_only = False
    target_content_types = ("application/json",)
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'updates')
    detail_url_patterns = ()
    exclude_url_patterns = ()

    custom_settings = {
        "LOG_LEVEL": "INFO",
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 0.5,
        "DOWNLOAD_TIMEOUT": 25,
        "RETRY_TIMES": 2,
        # 本站仅请求自身 WordPress REST 接口；在 fake-IP 代理环境下，域名解析到
        # 198.18.x.x / fd00:: 保留段，会被 SSRF 中间件误判，故显式放行本站域。
        "SSRF_ALLOWED_HOSTS": ['gassco.eu', '*.gassco.eu'],
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    max_pages = 80

    async def start(self):
        # Scrapy 2.13+ 的入口是 async 生成器 ``start()``（旧版 ``start_requests`` 已不再被调用）。
        for rest_base, section in _CONTENT_TYPES:
            url = f"{_API}/{rest_base}?per_page={_PER_PAGE}&page=1"
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={"rest_base": rest_base, "section": section, "page": 1},
            )

    def parse(self, response):
        rest_base = response.meta.get("rest_base", "posts")
        section = response.meta.get("section", "新闻")
        try:
            data = response.json()
        except (ValueError, TypeError):
            return
        if not isinstance(data, list) or not data:
            return

        for post in data:
            item = self._build_item(post, section)
            if item:
                yield item

        page = int(response.meta.get("page", 1))
        total_pages = _int_header(response, "X-WP-TotalPages")
        if (total_pages and page >= total_pages) or page >= self.max_pages:
            return
        next_url = f"{_API}/{rest_base}?per_page={_PER_PAGE}&page={page + 1}"
        yield scrapy.Request(
            next_url,
            callback=self.parse,
            meta={"rest_base": rest_base, "section": section, "page": page + 1},
        )

    def _build_item(self, post, section):
        title = _clean(html.unescape(_field(post, "title")))
        content_html = _field(post, "content")
        content = _strip_html(content_html)
        excerpt = _strip_html(_field(post, "excerpt"))
        link = _clean(_field(post, "link"))
        if not link:
            link = f"https://gassco.eu/en/home/?p={post.get('id') or ''}"
        if not title and not content:
            return None
        content_md = html_to_markdown(content_html, link)
        images = html_images(content_html, link)
        return {
            "title": title[:300] or "Untitled",
            "url": link,
            "content": content,
            "content_md": content_md,
            "summary": excerpt or content[:400],
            "images": images,
            "image_url": images[0] if images else "",
            "publish_time": _normalize_date(_field(post, "date")),
            "source": self.source_name,
            "source_site": self.source_site,
            "source_category": f"{self.source_category}·{section}",
            "domain": (urlparse(link).hostname or 'gassco.eu').lower().removeprefix("www."),
        }
