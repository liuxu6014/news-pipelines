"""'std.samr.gov.cn'（'标准化管理'）国家标准公告爬虫。

站点：'https://std.samr.gov.cn/'（国家标准信息公共服务平台）

首页的“标准检索”是纯 AJAX（bootstrap-table）搜索，但站内存在**服务端返回**的
“国家标准公告（通知公告/政策文件）”数据源：

- 列表：``https://std.samr.gov.cn/noc/search/nocGBPage?pageNumber=N&pageSize=100``
  返回 ``application/json``，每行含 ``CODE``（公告编号）、``TITLE``（公告标题）、
  ``NOTICE_DATE``（发布日期）、``PID``（详情主键）；
- 详情：``https://std.sacinfo.org.cn/gnoc/queryInfo?id=<PID>`` 是服务端渲染 HTML，
  正文落在 ``div.notice-content``（``p.ntitle`` 标题 / ``p.zhengwen`` 正文 /
  ``p.luokuan`` 落款与日期）。

本爬虫因此：1) 分页抓取公告列表 JSON；2) 逐条请求详情页解析标题/正文/日期；
3) 交给 Markdown 管线。
"""
import json
import re
from datetime import datetime
from urllib.parse import urlparse

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

# ---- 站点 XPath 选择器（详情页服务端渲染）----
LIST_ITEM_XPATH = ''
LIST_TITLE_XPATH = ".//a/text()"
LIST_LINK_XPATH = ".//a/@href"
DETAIL_TITLE_XPATH = ('//p[contains(@class,"ntitle")]//text()',)
DETAIL_CONTENT_XPATH = ('//div[contains(@class,"notice-content")]',)
DETAIL_DATE_XPATH = ('//p[contains(@class,"luokuan")]//text()',)
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

LIST_URL = 'https://std.samr.gov.cn/noc/search/nocGBPage'
DETAIL_URL = 'https://std.sacinfo.org.cn/gnoc/queryInfo?id={pid}'


def _clean(value):
    return _SPACE_RE.sub(" ", str(value or "").replace(" ", " ")).strip()


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


class XPathStdSamrGovCnSpider(scrapy.Spider):
    name = '133_std_samr_gov_cn'
    site_id = 'std.samr.gov.cn'
    site_name = 'std.samr.gov.cn'
    site_type = 'standard'
    language = 'zh-CN'
    source_title = '国家标准公告'
    source_name = '国家标准信息公共服务平台'
    source_category = '标准化管理'
    source_site = 'https://std.samr.gov.cn/'
    allowed_domains = ['samr.gov.cn', 'sacinfo.org.cn']
    entry_url = 'https://std.samr.gov.cn/'
    section_urls = ['https://std.samr.gov.cn/noc/nocGB']
    start_urls = ['https://std.samr.gov.cn/noc/nocGB']
    strict_news_only = True
    target_content_types = ("text/html", "application/json")
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'updates', 'xw', 'zx', 'tzgg', 'zwgk', 'gzyw', 'gzdt', 'xwzx')
    detail_url_patterns = DETAIL_PATTERNS
    exclude_url_patterns = (_BINARY_EXT.pattern,)

    PAGE_SIZE = 100

    custom_settings = {
        # 公告详情页由 std.sacinfo.org.cn（标准信息查询服务）服务端渲染，需显式放行。
        "SSRF_ALLOWED_HOSTS": ['samr.gov.cn', '*.samr.gov.cn', 'sacinfo.org.cn', '*.sacinfo.org.cn'],
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen = set()

    async def start(self):
        yield scrapy.Request(
            f"{LIST_URL}?pageNumber=1&pageSize={self.PAGE_SIZE}",
            callback=self.parse_list,
            meta={"page": 1},
        )

    def parse_list(self, response):
        """解析公告列表 JSON，逐条请求详情页，并跟进分页。"""
        page = int(response.meta.get("page", 1))
        try:
            data = json.loads(response.text)
        except (ValueError, json.JSONDecodeError):
            return
        rows = data.get("rows") or []
        total = int(data.get("total") or 0)
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = _clean(row.get("PID"))
            title = _clean(row.get("TITLE"))
            notice_date = _clean(row.get("NOTICE_DATE"))
            notice_code = _clean(row.get("CODE"))
            if not pid:
                continue
            yield scrapy.Request(
                DETAIL_URL.format(pid=pid),
                callback=self.parse_detail,
                meta={
                    "list_title": title,
                    "notice_date": notice_date,
                    "notice_code": notice_code,
                },
            )
        if page * self.PAGE_SIZE < total:
            yield scrapy.Request(
                f"{LIST_URL}?pageNumber={page + 1}&pageSize={self.PAGE_SIZE}",
                callback=self.parse_list,
                meta={"page": page + 1},
            )

    def parse_detail(self, response):
        title = _first_text(response, DETAIL_TITLE_XPATH) or _clean(response.meta.get("list_title"))
        content_node = self._extract_content_node(response)
        content = _node_text(content_node)
        if not content or len(content) < 60:
            return
        content_html = _node_html(content_node)
        content_md = html_to_markdown(content_html, response.url)
        images = html_images(content_html, response.url)
        publish_time = self._extract_date(response) or _normalize_date(response.meta.get("notice_date"))
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

    def _extract_content_node(self, response):
        # 优先使用站点专属的 DETAIL_CONTENT_XPATH，命中就不再落入通用兜底选择器。
        for xpath in DETAIL_CONTENT_XPATH:
            for node in response.xpath(xpath):
                text = _node_text(node)
                if text:
                    return node
        best_node = None
        best_len = -1
        for xpath in DEFAULT_CONTENT_XPATH:
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
        return ""
