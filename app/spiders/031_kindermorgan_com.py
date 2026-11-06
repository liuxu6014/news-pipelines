"""'Kinder Morgan Inc'（'国际管道'）独立爬虫 —— 直连 sitemap.xml，采集全部栏目。

站点：'https://www.kindermorgan.com/'
数据源：sitemap.xml（站点自身的 URL 清单接口）

「全部栏目」：从 sitemap 枚举全部内容型 URL，按 URL 路径归属栏目，写入
``source_category``（如 ``'国际管道'·栏目``）。详情页是服务端渲染 HTML，用
XPath 提取标题 / 日期 / 正文。日期按 meta / time / ``*[@class~='date']`` 等结构化
元素优先，兜底按 URL 内嵌日期或正文首个日期文本；无正文或非内容页自动跳过。

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

_SITEMAP_URLS = ['https://www.kindermorgan.com/sitemap.xml']

# 命中任一才算内容详情页（为空 = 不额外过滤）
_DETAIL_URL_RES = ['/Pages/Energy-Delivered/[^/]+$', '/Operations/KM-Treating/News/[^/]+$', '/Energy-Realities/[^/]+$']
# 命中任一即排除（列表页 / 导航 / 附件）
_EXCLUDE_URL_RES = ['\\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip|mp4)(\\?|$)']
# (URL 正则, 栏目名)：首个命中者写入 source_category
_SECTION_RULES = [('/Energy-Delivered/', 'Energy Delivered 故事'), ('/KM-Treating/News/', 'KM-Treating 新闻'), ('/Energy-Realities/', '能源现实')]

# 站点专属选择器，前置到通用选择器之前
_DATE_XPATHS = []
_CONTENT_XPATHS = []

_ALLOW_BODY_DATE = True

_SPACE_RE = re.compile(r"\s+")
_DATE_TEXT_RE = re.compile(
    r"(?:(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2}|"
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\.?\s+20\d{2}|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})"
)
_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
    "%d %B %Y", "%d %b %Y", "%d %B, %Y", "%d %b, %Y",
)

_GENERIC_DATE_XPATHS = (
    "//meta[@property='article:published_time']/@content",
    "//meta[@property='article:modified_time']/@content",
    "//meta[@name='date']/@content",
    "//meta[@name='dc.date']/@content",
    "//meta[@name='pubdate']/@content",
    "//meta[@name='publishdate']/@content",
    "//meta[@itemprop='datePublished']/@content",
    "//time/@datetime",
    "//time//text()",
    "//*[contains(@class,'publish-date')]//text()",
    "//*[contains(@class,'article-date')]//text()",
    "//*[contains(@class,'post-date')]//text()",
    "//*[contains(@class,'entry-date')]//text()",
    "//*[contains(@class,'story-date')]//text()",
    "//*[contains(@class,'date')]//text()",
)

_GENERIC_CONTENT_XPATHS = (
    "//article",
    "//main",
    "//div[contains(@class,'article-body')]",
    "//div[contains(@class,'article-content')]",
    "//div[contains(@class,'rich-text')]",
    "//div[contains(@class,'field--name-body')]",
    "//div[contains(@class,'content-section')]",
    "//div[contains(@class,'story-content')]",
    "//div[contains(@class,'entry-content')]",
    "//div[contains(@class,'post-content')]",
    "//div[contains(@class,'body-content')]",
    "//div[contains(@class,'wysiwyg')]",
    "//div[contains(@class,'text-content')]",
)


def _clean(value):
    return _SPACE_RE.sub(" ", str(value or "").replace("\u00a0", " ")).strip()


def _node_text(node):
    parts = node.xpath(
        ".//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)]"
    ).getall()
    return _clean(" ".join(parts))


def _node_html(node):
    if node is None:
        return ""
    return node.get() or ""


def _parse_date_text(raw):
    text = _clean(raw)
    if not text:
        return ""
    text = re.sub(r"\b(st|nd|rd|th)\b", "", text, flags=re.I)
    text = re.sub(r"([A-Za-z]{3,9})\.", r"\1", text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


def _date_from(value):
    match = _DATE_TEXT_RE.search(_clean(value))
    if not match:
        return ""
    return _parse_date_text(match.group(0))


def _date_from_url(url):
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", url)
    if match:
        try:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        except ValueError:
            pass
    match = re.search(r"(?:^|[/_-])(20\d{2})(\d{2})(\d{2})(?:[/_-]|$)", url)
    if match:
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    match = re.search(r"(?:^|[/_-])(2\d)(\d{2})(\d{2})(?:[/_-]|$)", url)
    if match:
        y, m, d = 2000 + int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    match = re.search(r"/(20\d{2})/(\d{1,2})/", url)
    if match:
        try:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-01"
        except ValueError:
            pass
    return ""


class KindermorganComSpider(scrapy.Spider):
    name = '031_kindermorgan_com'
    site_id = 'kindermorgan.com'
    site_name = 'Kinder Morgan Inc'
    site_type = 'pipe'
    language = 'en'
    source_title = 'Kinder Morgan Inc'
    source_name = 'Kinder Morgan Inc'
    source_category = '国际管道'
    source_site = 'https://www.kindermorgan.com/'
    allowed_domains = ['kindermorgan.com']
    entry_url = 'https://www.kindermorgan.com/'
    section_urls = ['https://www.kindermorgan.com/sitemap.xml']
    start_urls = ['https://www.kindermorgan.com/sitemap.xml']
    strict_news_only = False
    target_content_types = ("text/xml", "application/xml", "application/rss+xml")
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'blog', 'release', 'article', 'announcement', 'event', 'publication')
    detail_url_patterns = ['/Pages/Energy-Delivered/[^/]+$', '/Operations/KM-Treating/News/[^/]+$', '/Energy-Realities/[^/]+$']
    exclude_url_patterns = ['\\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip|mp4)(\\?|$)']

    custom_settings = {
        "LOG_LEVEL": "INFO",
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 0.5,
        "DOWNLOAD_TIMEOUT": 25,
        "RETRY_TIMES": 2,
        # 本站仅请求自身 sitemap 与详情页；在 fake-IP 代理环境下，域名解析到
        # 198.18.x.x / fd00:: 保留段，会被 SSRF 中间件误判，故显式放行本站域。
        "SSRF_ALLOWED_HOSTS": ['kindermorgan.com', '*.kindermorgan.com'],
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
        # Scrapy 2.13+ 的入口是 async 生成器 ``start()``（旧版 ``start_requests`` 已不再被调用）。
        for url in _SITEMAP_URLS:
            yield scrapy.Request(url, callback=self.parse_sitemap)

    def parse_sitemap(self, response):
        selector = Selector(text=response.text, type="xml")
        # sitemap index：递归跟随子 sitemap
        subs = selector.xpath("//*[local-name()='sitemap']/*[local-name()='loc']/text()").getall()
        if subs:
            for sub in subs:
                sub = sub.strip()
                if sub:
                    yield scrapy.Request(sub, callback=self.parse_sitemap)
            return
        for loc in selector.xpath("//*[local-name()='url']/*[local-name()='loc']/text()").getall():
            url = loc.strip()
            if not url or url in self._seen:
                continue
            self._seen.add(url)
            if self._excluded(url) or not self._is_detail(url):
                continue
            yield scrapy.Request(url, callback=self.parse_detail, meta={"url": url})

    def _excluded(self, url):
        return any(re.search(pat, url, re.I) for pat in _EXCLUDE_URL_RES)

    def _is_detail(self, url):
        if not _DETAIL_URL_RES:
            return True
        return any(re.search(pat, url, re.I) for pat in _DETAIL_URL_RES)

    def parse_detail(self, response):
        url = response.meta.get("url") or response.url
        selector = Selector(response=response)
        title = self._extract_title(selector)
        content_node = self._extract_content_node(selector)
        content = _node_text(content_node)
        if not title or not content:
            return
        content_html = _node_html(content_node)
        content_md = html_to_markdown(content_html, url)
        images = html_images(content_html, url)
        date_text = self._extract_date(selector, url)
        section = self._section_for(url)
        yield {
            "title": title[:300],
            "url": url,
            "content": content,
            "content_md": content_md,
            "summary": content[:400],
            "images": images,
            "image_url": images[0] if images else "",
            "publish_time": date_text,
            "source": self.source_name,
            "source_site": self.source_site,
            "source_category": f"{self.source_category}·{section}",
            "domain": (urlparse(url).hostname or 'kindermorgan.com').lower().removeprefix("www."),
        }

    _GENERIC_TITLES = {
        "news", "news release", "news releases", "press release", "press releases",
        "media advisory", "media statement", "media statements", "media center",
        "announcement", "announcements", "statement", "statements", "blog", "article",
        "articles", "stories", "newsroom", "insights", "updates",
        "case study", "case studies", "media release", "media releases",
        "video", "videos", "webinar", "webinars", "white paper", "white papers",
        "event", "events", "publication", "publications", "paper", "papers",
        "press", "media", "report", "reports", "newsletter", "podcast", "podcasts",
        "brochure", "brochures", "datasheet", "datasheets", "fact sheet", "fact sheets",
    }

    def _extract_title(self, selector):
        best = ""
        for node in selector.xpath("//h1"):
            text = _node_text(node)
            if len(text) > len(best):
                best = text
        best = best.strip().rstrip("|").strip()
        if best and best.lower() not in self._GENERIC_TITLES:
            return html.unescape(best)
        for xp in ("//meta[@property='og:title']/@content", "//title"):
            value = selector.xpath(xp).get()
            if value:
                return html.unescape(_clean(value))
        return html.unescape(best) if best else ""

    def _extract_date(self, selector, url):
        for xp in list(_DATE_XPATHS) + list(_GENERIC_DATE_XPATHS):
            for value in selector.xpath(xp).getall():
                parsed = _date_from(value)
                if parsed:
                    return parsed
        parsed = _date_from_url(url)
        if parsed:
            return parsed
        if _ALLOW_BODY_DATE:
            body = " ".join(selector.xpath("//body//text()").getall())
            return _date_from(body)
        return ""

    def _extract_content_node(self, selector):
        for xp in list(_CONTENT_XPATHS) + list(_GENERIC_CONTENT_XPATHS):
            for node in selector.xpath(xp):
                text = _node_text(node)
                if len(text) >= 80:
                    return node
        # 兜底：正文通常是最长的、包含段落或子标题的 div（排除包裹整页的容器）。
        total = len(_clean(" ".join(selector.xpath("//body//text()").getall()))) or 1
        best = ""
        best_node = None
        for node in selector.xpath("//div[.//p or .//h2 or .//h3]"):
            text = _node_text(node)
            if len(text) > len(best) and len(text) < total * 0.95:
                best = text
                best_node = node
        return best_node

    def _section_for(self, url):
        for pattern, label in _SECTION_RULES:
            if re.search(pattern, url, re.I):
                return label
        return "新闻"
