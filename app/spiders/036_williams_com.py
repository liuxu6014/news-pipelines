"""'Williams Cos Inc'（'国际管道'）独立爬虫 —— 直连 WordPress REST API，采集新闻。

站点：'https://www.williams.com/'
数据源：'https://www.williams.com/wp-json/wp/v2/posts'（WordPress REST API）

本脚本自包含全部抓取/解析逻辑，仅依赖 scrapy 与 app.html_markdown（HTML→Markdown
转换），不继承任何项目级通用爬虫基类。接口一次返回完整字段（title/content/excerpt/
date/link），无需再抓详情页；分页依据响应头 ``X-WP-TotalPages``，取不到时以空列表兜底。
"""
import html
import re
from datetime import datetime
from urllib.parse import urlparse

import scrapy
from scrapy import Selector

from app.html_markdown import html_images, html_to_markdown

_SPACE_RE = re.compile(r"\s+")
_BINARY_EXT = re.compile(
    r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|jpg|jpeg|png|gif|mp4|mp3|wav)(\?.*)?$",
    re.I,
)
_DATE_RE = re.compile(
    r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)
_URL_DATE = re.compile(r"20\d{2}[-_/]?\d{0,2}[-_/]?\d{0,2}")

# ---- 站点 XPath 选择器（按需微调）----
LIST_ITEM_XPATH = ''
LIST_TITLE_XPATH = ".//a/text()"
LIST_LINK_XPATH = ".//a/@href"
DETAIL_TITLE_XPATH = ('//h1//text()',)
DETAIL_CONTENT_XPATH = ()
DETAIL_DATE_XPATH = ()
DETAIL_PATTERNS = ()

DEFAULT_CONTENT_XPATH = (
    "//article",
    "//div[contains(@class,'TRS_Editor')]",
    "//div[@id='TRS_AUTOADD']",
    "//div[@id='UCAP-CONTENT']",
    "//div[@id='js_content']",
    "//div[@id='article_content']",
    "//div[contains(@class,'wzcon')]",
    "//div[contains(@class,'article-content')]",
    "//div[contains(@class,'article_content')]",
    "//div[contains(@class,'article-body')]",
    "//div[contains(@class,'article-con')]",
    "//div[contains(@class,'detail-content')]",
    "//div[contains(@class,'detail_con')]",
    "//div[contains(@class,'main-content')]",
    "//div[contains(@class,'news-content')]",
    "//div[contains(@class,'news_content')]",
    "//div[contains(@class,'news-text')]",
    "//div[contains(@class,'pages_content')]",
    "//div[contains(@class,'content')]",
    "//div[contains(@id,'content')]",
    "//div[contains(@class,'zoom')]",
    "//div[@id='zoom']",
    "//div[@id='content']",
    "//div[@class='main']",
)

DEFAULT_DATE_XPATH = (
    "//meta[@property='article:published_time']/@content",
    "//meta[@name='article:published_time']/@content",
    "//meta[@name='PubDate']/@content",
    "//meta[@name='pubdate']/@content",
    "//meta[@itemprop='datePublished']/@content",
    "//meta[@name='dc.date']/@content",
    "//meta[@name='DC.date']/@content",
    "//meta[@property='dc:date']/@content",
    "//time/@datetime",
    "//time//text()",
    "//*[contains(@class,'time')]//text()",
    "//*[contains(@class,'publish')]//text()",
    "//span[contains(@class,'date')]//text()",
)


def _clean(value):
    return _SPACE_RE.sub(" ", str(value or "").replace("\u00a0", " ")).strip()


def _node_text(node):
    if node is None:
        return ""
    parts = node.xpath(
        ".//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)]"
    ).getall()
    return _clean(" ".join(parts))


def _node_html(node):
    if node is None:
        return ""
    return node.get() or ""


def _first_text(response, xpaths):
    for xpath in xpaths:
        for value in response.xpath(xpath).getall():
            text = _clean(value)
            if text:
                return text
    return ""


def _normalize_date(value):
    text = _clean(value)
    if not text:
        return ""
    match = _DATE_RE.search(text)
    if not match:
        try:
            return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return ""
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    second = int(match.group(6) or 0)
    try:
        return datetime(year, month, day, hour, minute, second).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


_API = 'https://www.williams.com/wp-json/wp/v2/posts'
_PER_PAGE = 50


def _field(post, name, sub="rendered"):
    """兼容 WP REST 中字段既可能是 dict（{rendered: ...}）也可能是纯字符串。"""
    if not isinstance(post, dict):
        return ""
    value = post.get(name)
    if isinstance(value, dict):
        return value.get(sub) or ""
    return value or ""


def _strip_html(fragment):
    """用 XPath 从 HTML 片段提取纯文本（跳过 script/style/noscript）。"""
    if not fragment:
        return ""
    selector = Selector(text=str(fragment))
    parts = selector.xpath(
        "//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)]"
    ).getall()
    return _clean(" ".join(parts))


def _normalize_wp_date(value):
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


class XPathWilliamsComSpider(scrapy.Spider):
    name = '036_williams_com'
    site_id = 'williams.com'
    site_name = 'Williams Cos Inc'
    site_type = 'pipe'
    language = 'en'
    source_title = 'Williams Cos Inc'
    source_name = 'Williams Cos Inc'
    source_category = '国际管道'
    source_site = 'https://www.williams.com/'
    allowed_domains = ['williams.com']
    entry_url = 'https://www.williams.com/'
    section_urls = ['https://www.williams.com/wp-json/wp/v2/posts']
    start_urls = ['https://www.williams.com/wp-json/wp/v2/posts?per_page=50&page=1']
    strict_news_only = False
    target_content_types = ("application/json",)
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'updates', 'xw', 'zx', 'tzgg', 'zwgk', 'gzyw', 'gzdt', 'xwzx')
    detail_url_patterns = DETAIL_PATTERNS
    exclude_url_patterns = (_BINARY_EXT.pattern,)

    custom_settings = {
        "SSRF_ALLOWED_HOSTS": ['williams.com', '*.williams.com'],
        "LOG_LEVEL": "INFO",
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 0.5,
        "DOWNLOAD_TIMEOUT": 25,
        "RETRY_TIMES": 2,
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    max_pages = 80
    max_depth = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen = set()

    async def start(self):
        # Scrapy 2.13+ 的入口是 async 生成器 ``start()``（旧版 ``start_requests`` 已不再被调用）。
        yield scrapy.Request(
            f"{_API}?per_page={_PER_PAGE}&page=1",
            callback=self.parse,
            meta={"page": 1},
        )

    def parse(self, response):
        try:
            data = response.json()
        except (ValueError, TypeError):
            return
        if not isinstance(data, list) or not data:
            return
        for post in data:
            item = self._build_item(post)
            if item:
                yield item
        page = int(response.meta.get("page", 1))
        total_pages = _int_header(response, "X-WP-TotalPages")
        if (total_pages and page >= total_pages) or page >= self.max_pages:
            return
        yield scrapy.Request(
            f"{_API}?per_page={_PER_PAGE}&page={page + 1}",
            callback=self.parse,
            meta={"page": page + 1},
        )

    def _build_item(self, post):
        title = _clean(html.unescape(_field(post, "title")))
        content_html = _field(post, "content")
        content = _strip_html(content_html)
        excerpt = _strip_html(_field(post, "excerpt"))
        link = _clean(_field(post, "link"))
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
            "publish_time": _normalize_wp_date(_field(post, "date")),
            "source": self.source_name,
            "source_site": self.source_site,
            "source_category": self.source_category,
            "domain": (urlparse(link).hostname or "williams.com").lower().removeprefix("www."),
        }

    def parse_detail(self, response):
        title = _first_text(response, DETAIL_TITLE_XPATH) or _clean(response.meta.get("list_title"))
        content_node = self._extract_content_node(response)
        content = _node_text(content_node)
        if not content or len(content) < 80:
            return
        content_html = _node_html(content_node)
        content_md = html_to_markdown(content_html, response.url)
        images = html_images(content_html, response.url)
        publish_time = self._extract_date(response)
        yield {
            "title": title[:300],
            "url": response.url,
            "content": content,
            "content_md": content_md,
            "summary": content[:400],
            "images": images,
            "image_url": images[0] if images else "",
            "publish_time": publish_time,
            "source": self.source_name,
            "source_site": self.source_site,
            "source_category": self.source_category,
            "domain": (urlparse(response.url).hostname or "").lower().removeprefix("www."),
        }

    def _iter_links(self, response):
        if LIST_ITEM_XPATH:
            for node in response.xpath(LIST_ITEM_XPATH):
                link = (node.xpath(LIST_LINK_XPATH).get() or "").strip()
                title = _clean(node.xpath(LIST_TITLE_XPATH).get())
                if link and title:
                    yield link, title
            return
        for node in response.xpath("//a[@href]"):
            link = (node.xpath("@href").get() or "").strip()
            title = _node_text(node)
            if link and title:
                yield link, title

    def _same_host(self, url):
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if not host:
            return False
        return any(
            host == d.removeprefix("www.") or host.endswith("." + d.removeprefix("www."))
            for d in self.allowed_domains
        )

    def _is_article(self, url):
        path = urlparse(url).path
        if _BINARY_EXT.search(path):
            return False
        if DETAIL_PATTERNS:
            return any(re.search(pattern, path) for pattern in DETAIL_PATTERNS)
        if not re.search(r"\.(?:htm|html|shtml)$", path):
            return False
        return bool(_URL_DATE.search(url) or re.search(r"(?:content|art)_?\d+", path, re.I))

    def _extract_content_node(self, response):
        xpaths = [x for x in DETAIL_CONTENT_XPATH if x]
        xpaths.extend(DEFAULT_CONTENT_XPATH)
        best_node = None
        best_len = -1
        for xpath in xpaths:
            for node in response.xpath(xpath):
                text = _node_text(node)
                if text and len(text) > best_len:
                    best_len = len(text)
                    best_node = node
        return best_node

    def _extract_date(self, response):
        xpaths = [x for x in DETAIL_DATE_XPATH if x]
        xpaths.extend(DEFAULT_DATE_XPATH)
        for xpath in xpaths:
            for value in response.xpath(xpath).getall():
                normalized = _normalize_date(value)
                if normalized:
                    return normalized
        for match in re.finditer(
            r"(?:发布时间|发布日期|日期|时间)\s*[:：]?\s*"
            r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?(?:\s+\d{1,2}:\d{2})?)",
            response.text[:30000],
        ):
            normalized = _normalize_date(match.group(1))
            if normalized:
                return normalized
        return ""
