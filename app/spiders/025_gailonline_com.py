"""'GAIL (India) -Gas Transmission'（'国际管道'）独立 XPath 爬虫。

站点：'https://gailonline.com/'
本脚本自包含全部抓取/解析逻辑，仅依赖 scrapy 与 app.html_markdown（HTML→Markdown
转换），不继承任何项目级通用爬虫基类。解析全部通过 ``response.xpath(...)`` 完成。

XPath 选择器为初始值，需按站点实际页面结构微调后再投入长期采集。
"""
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import scrapy

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
DETAIL_CONTENT_XPATH = ("//div[contains(@class,'pop-body')]",)
DETAIL_DATE_XPATH = ()
DETAIL_PATTERNS = (r"PressRelease.*\.html",)

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


class XPathGailonlineComSpider(scrapy.Spider):
    name = '025_gailonline_com'
    site_id = 'gailonline.com'
    site_name = 'GAIL (India) -Gas Transmission'
    site_type = 'pipe'
    language = 'en'
    source_title = 'GAIL (India) -Gas Transmission'
    source_name = 'GAIL (India) -Gas Transmission'
    source_category = '国际管道'
    source_site = 'https://gailonline.com/'
    allowed_domains = ['gailonline.com']
    entry_url = 'https://gailonline.com/'
    section_urls = ['https://gailonline.com/PressRelease.html']
    start_urls = ['https://gailonline.com/PressRelease.html']
    strict_news_only = True
    target_content_types = ("text/html",)
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'updates', 'xw', 'zx', 'tzgg', 'zwgk', 'gzyw', 'gzdt', 'xwzx')
    detail_url_patterns = DETAIL_PATTERNS
    exclude_url_patterns = (_BINARY_EXT.pattern,)

    custom_settings = {
        "SSRF_ALLOWED_HOSTS": ['gailonline.com', '*.gailonline.com'],
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
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, meta={"depth": 0})

    def parse(self, response):
        depth = int(response.meta.get("depth", 0))
        if len(self._seen) >= self.max_pages:
            return
        for href, title in self._iter_links(response):
            url = urljoin(response.url, href)
            if not self._same_host(url) or url in self._seen:
                continue
            self._seen.add(url)
            if self._is_article(url):
                yield scrapy.Request(
                    url, callback=self.parse_detail, meta={"list_title": title, "depth": depth + 1}
                )
            elif depth < self.max_depth:
                yield scrapy.Request(url, callback=self.parse, meta={"depth": depth + 1})

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
