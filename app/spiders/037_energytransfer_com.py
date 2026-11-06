"""'energy transfer'（'国际管道'）JSON Newsroom 爬虫。

站点：'https://www.energytransfer.com/'

本站是 React SPA：``/``、``/newsroom/``、``/sitemap.xml`` 等任意路径都返回同一个约 2.4MB
的 JS 外壳，正文由前端渲染，robots.txt 也被 F5 WAF 拦截（403）。但站内其实存在一个
服务端 JSON 新闻接口（Nasdaq GCS 数据源，同源代理）：

- 列表：``https://www.energytransfer.com/nasdaq/newsroom?page=N``
  返回 ``application/json``，含 ``title`` / ``releaseDate`` / ``teaser`` / 正文链接；
- 正文：列表项 ``body[0].link.url`` 指向 ``clientapi.gcs-web.com/.../news/<id>/html``，
  返回 ``{"data": "<html>..."}``，即完整新闻稿 HTML。

本爬虫因此：1) 抓取新闻列表（分页）；2) 逐条请求正文 JSON，解析 HTML 正文；3) 交给
Markdown 管线。
"""
import json
import re
from datetime import datetime
from urllib.parse import urlparse

import scrapy

from app.html_markdown import html_images, html_plain_text, html_to_markdown

_SPACE_RE = re.compile(r"\s+")
_BINARY_EXT = re.compile(
    r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|jpg|jpeg|png|gif|mp4|mp3|wav)(\?.*)?$",
    re.I,
)
_DATE_RE = re.compile(
    r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)
_PAGE_RE = re.compile(r"[?&]page=(\d+)")

NEWSROOM_URL = 'https://www.energytransfer.com/nasdaq/newsroom'


def _clean(value):
    return _SPACE_RE.sub(" ", str(value or "").replace(" ", " ")).strip()


def _iso_date(value):
    text = _clean(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        match = _DATE_RE.search(text)
        if not match:
            return ""
        try:
            dt = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                int(match.group(4) or 0), int(match.group(5) or 0), int(match.group(6) or 0),
            )
        except ValueError:
            return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class XPathEnergytransferComSpider(scrapy.Spider):
    name = '037_energytransfer_com'
    site_id = 'energytransfer.com'
    site_name = 'energy transfer'
    site_type = 'pipe'
    language = 'en'
    source_title = 'energy transfer'
    source_name = 'energy transfer'
    source_category = '国际管道'
    source_site = 'https://www.energytransfer.com/'
    allowed_domains = ['energytransfer.com', 'gcs-web.com']
    entry_url = 'https://www.energytransfer.com/'
    section_urls = ['https://www.energytransfer.com/']
    start_urls = ['https://www.energytransfer.com/']
    strict_news_only = True
    target_content_types = ("text/html", "application/json")
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'updates', 'xw', 'zx', 'tzgg', 'zwgk', 'gzyw', 'gzdt', 'xwzx')
    detail_url_patterns = ()
    exclude_url_patterns = (_BINARY_EXT.pattern,)

    custom_settings = {
        # 正文数据由 Nasdaq GCS（clientapi.gcs-web.com）服务端提供，需显式放行该数据域。
        "SSRF_ALLOWED_HOSTS": ['energytransfer.com', '*.energytransfer.com', 'gcs-web.com', '*.gcs-web.com'],
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
        self._seen_articles = set()

    async def start(self):
        yield scrapy.Request(
            NEWSROOM_URL + '?page=1', callback=self.parse_list, meta={"page": 1}
        )

    def parse_list(self, response):
        """解析新闻列表 JSON，逐条请求正文，并跟进下一页。"""
        page = int(response.meta.get("page", 1))
        try:
            data = json.loads(response.text)
        except (ValueError, json.JSONDecodeError):
            return
        items = data.get("data") or []
        links = data.get("links") or {}
        last_page = page
        if isinstance(links.get("last"), str):
            match = _PAGE_RE.search(links["last"])
            if match:
                last_page = int(match.group(1))
        for item in items:
            if not isinstance(item, dict):
                continue
            article_url = (item.get("link") or {}).get("hostedUrl") or ""
            title = _clean(item.get("title"))
            publish_time = _iso_date((item.get("releaseDate") or {}).get("date"))
            teaser = _clean(item.get("teaser"))
            body_url = ""
            for entry in item.get("body") or []:
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") == "html" and (entry.get("link") or {}).get("url"):
                    body_url = entry["link"]["url"]
                    break
            if not article_url or article_url in self._seen_articles:
                continue
            self._seen_articles.add(article_url)
            if body_url:
                yield scrapy.Request(
                    body_url,
                    callback=self.parse_detail,
                    meta={
                        "article_url": article_url,
                        "title": title,
                        "publish_time": publish_time,
                        "teaser": teaser,
                    },
                )
            elif teaser:
                # 无正文链接时，用 teaser 作为正文兜底。
                yield {
                    "title": title[:300],
                    "url": article_url,
                    "content": teaser,
                    "content_md": teaser,
                    "summary": teaser[:400],
                    "images": [],
                    "image_url": "",
                    "publish_time": publish_time,
                    "source": self.source_name,
                    "source_site": self.source_site,
                    "source_category": self.source_category,
                    "domain": (urlparse(article_url).hostname or "").lower().removeprefix("www."),
                }
        if page < last_page:
            yield scrapy.Request(
                NEWSROOM_URL + f'?page={page + 1}', callback=self.parse_list, meta={"page": page + 1}
            )

    def parse_detail(self, response):
        """解析正文 JSON（``{"data": "<html>"}``），提取正文并交给 Markdown 管线。"""
        try:
            data = json.loads(response.text)
        except (ValueError, json.JSONDecodeError):
            return
        html = data.get("data") if isinstance(data, dict) else ""
        if not isinstance(html, str) or not html.strip():
            return
        article_url = response.meta.get("article_url") or response.url
        title = _clean(response.meta.get("title"))
        publish_time = response.meta.get("publish_time") or ""
        teaser = _clean(response.meta.get("teaser"))
        content = html_plain_text(html)
        if len(content) < 80 and teaser:
            content = teaser
        if not content or len(content) < 80:
            return
        content_md = html_to_markdown(html, article_url)
        images = html_images(html, article_url)
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
