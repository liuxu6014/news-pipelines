"""'Snam SpA'（'国际管道'）Sitemap + AEM ``.model.json`` 爬虫。

站点：'https://www.snam.it/en/home.html'

本站基于 Adobe Experience Manager（AEM）SPA：文章页面的 HTML 只是 JS 空壳（正文由前端渲染），
但站点暴露真实的 ``https://www.snam.it/sitemap.xml``，且每篇文章的完整内容可由 AEM 的
``<页面路径>.model.json``（把 ``.html`` 替换为 ``.model.json``）以 JSON 形式服务端返回。
标题、正文、发布时间都落在 content fragment（``content_fragment_new``）里。

本爬虫因此：

1. 抓取 ``https://www.snam.it/sitemap.xml`` 的所有 ``<loc>``；
2. 按 ``DETAIL_PATTERNS`` 匹配英文新闻 / 新闻稿（comunicati-stampa）文章 URL；
3. 请求对应 ``.model.json``，解析 JSON 得到标题、正文、发布时间，再交给 Markdown 管线。

本脚本自包含全部抓取/解析逻辑，仅依赖 scrapy 与 app.html_markdown。
"""
import json
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import scrapy

from app.html_markdown import html_images, html_plain_text, html_to_markdown

_SPACE_RE = re.compile(r"\s+")
_BINARY_EXT = re.compile(
    r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|jpg|jpeg|png|gif|mp4|mp3|wav)(\?.*)?$",
    re.I,
)

# ---- 站点文章 URL 匹配规则（sitemap 中的英文新闻/新闻稿正文页）----
DETAIL_PATTERNS = (
    r"/en/media/news-and-press-releases/news/\d{4}/",
    r"/en/media/news-and-press-releases/comunicati-stampa/\d{4}/",
    r"/en/our-businesses/news/\d{4}/",
)

_DETAIL_RES = tuple(re.compile(p) for p in DETAIL_PATTERNS)


def _clean(value):
    return _SPACE_RE.sub(" ", str(value or "").replace(" ", " ")).strip()


def _json_date_ms(value):
    """AEM content fragment 的 calendar 字段是 epoch 毫秒，转成入库格式。"""
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000.0, UTC).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return ""


class XPathSnamItSpider(scrapy.Spider):
    name = '034_snam_it'
    site_id = 'snam.it'
    site_name = 'Snam SpA'
    site_type = 'pipe'
    language = 'en'
    source_title = 'Snam SpA'
    source_name = 'Snam SpA'
    source_category = '国际管道'
    source_site = 'https://www.snam.it/en/home.html'
    allowed_domains = ['snam.it']
    entry_url = 'https://www.snam.it/en/home.html'
    section_urls = ['https://www.snam.it/en/home.html']
    start_urls = ['https://www.snam.it/en/home.html']
    strict_news_only = True
    target_content_types = ("text/html", "application/json", "application/xml", "text/xml")
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'updates', 'xw', 'zx', 'tzgg', 'zwgk', 'gzyw', 'gzdt', 'xwzx')
    detail_url_patterns = DETAIL_PATTERNS
    exclude_url_patterns = (_BINARY_EXT.pattern,)

    SITEMAP_URL = 'https://www.snam.it/sitemap.xml'

    custom_settings = {
        "SSRF_ALLOWED_HOSTS": ['snam.it', '*.snam.it'],
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
        yield scrapy.Request(self.SITEMAP_URL, callback=self.parse_sitemap)

    def parse_sitemap(self, response):
        """解析 sitemap.xml / sitemapindex.xml 的 <loc>，递归跟进嵌套 sitemap。"""
        for loc in response.xpath("//*[local-name()='loc']/text()").getall():
            url = (loc or "").strip()
            if not url:
                continue
            if url in self._seen:
                continue
            self._seen.add(url)
            path = urlparse(url).path.lower()
            if path.endswith(".xml"):
                yield scrapy.Request(url, callback=self.parse_sitemap)
            elif self._is_article(url):
                yield scrapy.Request(
                    self._model_url(url),
                    callback=self.parse_detail,
                    meta={"article_url": url},
                )

    def parse_detail(self, response):
        """解析 AEM ``.model.json``，提取标题 / 正文 / 发布时间。"""
        try:
            data = json.loads(response.text)
        except (ValueError, json.JSONDecodeError):
            return
        fragment = self._find_content_fragment(data)
        if not fragment:
            return
        elements = fragment.get("elements") or {}
        desc_html = (elements.get("description") or {}).get("value") or ""
        if not desc_html:
            return
        article_url = response.meta.get("article_url") or response.url
        content = html_plain_text(desc_html)
        if not content or len(content) < 80:
            return
        content_md = html_to_markdown(desc_html, article_url)
        images = html_images(desc_html, article_url)
        title = _clean(fragment.get("pageTitle")) or _clean(data.get("title"))
        publish_time = _json_date_ms((elements.get("datePublication") or {}).get("value"))
        yield {
            "title": title[:300],
            "url": article_url,
            "content": content,
            "content_md": content_md,
            "summary": content[:400],
            "images": images,
            "image_url": images[0] if images else "",
            "publish_time": publish_time,
            "source": self.source_name,
            "source_site": self.source_site,
            "source_category": self.source_category,
            "domain": (urlparse(article_url).hostname or "").lower().removeprefix("www."),
        }

    def _is_article(self, url):
        path = urlparse(url).path
        if _BINARY_EXT.search(path):
            return False
        return any(r.search(path) for r in _DETAIL_RES)

    @staticmethod
    def _model_url(url):
        """AEM 的内容模型端点：``/page.html`` -> ``/page.model.json``。"""
        base = url[:-5] if url.endswith(".html") else url
        return base + ".model.json"

    @staticmethod
    def _find_content_fragment(node):
        """递归定位 ``content_fragment_new``（含 ``elements``），兼容新旧模板路径。"""
        if isinstance(node, dict):
            candidate = node.get("content_fragment_new")
            if isinstance(candidate, dict) and "elements" in candidate:
                return candidate
            for value in node.values():
                found = XPathSnamItSpider._find_content_fragment(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = XPathSnamItSpider._find_content_fragment(value)
                if found is not None:
                    return found
        return None
