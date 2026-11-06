"""生成「WordPress REST API」直连的独立站点爬虫（平铺到 app/spiders/）。

每个生成的脚本自包含全部逻辑，仅依赖 scrapy + 标准库，不继承任何项目级基类。
遵循 scrapy-spider skill 约定：

- 入口用 ``async def start()``（本项目 Scrapy 2.13+ 已不再调用 ``start_requests``）。
- 逐栏目枚举内容型 post type（采集「全部栏目」），``source_category`` 写为
  ``<站点分类>·<栏目>``。
- 列表接口一次返回完整字段，按响应头 ``X-WP-TotalPages`` 分页，空列表兜底停止。
- ``content.rendered`` / ``excerpt.rendered`` 用 ``scrapy.Selector`` 的 XPath 提取纯文本。
- ``custom_settings["SSRF_ALLOWED_HOSTS"]`` 放行本站域（规避 fake-IP 代理下 SSRF 误判）。

用法：``uv run python tools/generate_wp_spiders.py``
"""
from __future__ import annotations

from pathlib import Path

SPIDERS_DIR = Path(__file__).resolve().parents[1] / "app" / "spiders"

# (文件名, 配置)。content_types: (rest_base, 栏目中文名)
SITES = [
    dict(
        file="004_cooperservices_com",
        site_id="cooperservices.com",
        site_name="Cooper Machinery Services",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="https://www.cooperservices.com/",
        allowed_domains=["cooperservices.com"],
        api="https://www.cooperservices.com/wp-json/wp/v2",
        content_types=[("posts", "新闻"), ("event_listing", "活动"), ("portfolio", "案例")],
    ),
    dict(
        file="013_mears_net",
        site_id="mears.net",
        site_name="Mears Group, Inc.",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="https://mears.net/division/pipeline-integrity/",
        allowed_domains=["mears.net"],
        api="https://www.mears.net/wp-json/wp/v2",
        content_types=[("posts", "新闻")],
    ),
    dict(
        file="014_previan_com",
        site_id="previan.com",
        site_name="Previan",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="https://previan.com/",
        allowed_domains=["previan.com"],
        api="https://previan.com/wp-json/wp/v2",
        content_types=[("posts", "新闻")],
    ),
    dict(
        file="027_gasgrid_fi",
        site_id="gasgrid.fi",
        site_name="Gasgrid Finland",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://gasgrid.fi/en/",
        allowed_domains=["gasgrid.fi"],
        api="https://gasgrid.fi/wp-json/wp/v2",
        content_types=[
            ("posts", "新闻"),
            ("projects", "项目"),
            ("podcast", "播客"),
            ("materials", "材料"),
            ("events", "活动"),
            ("bulletins", "公告"),
        ],
    ),
    dict(
        file="028_gassco_eu",
        site_id="gassco.eu",
        site_name="Gassco",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://gassco.eu/en/home/",
        allowed_domains=["gassco.eu"],
        api="https://gassco.eu/wp-json/wp/v2",
        content_types=[("posts", "新闻"), ("projects", "项目")],
    ),
]


def _q(value):
    return repr(str(value))


def _content_types_repr(pairs):
    return "(\n" + "\n".join(f"        ({_q(r)}, {_q(label)})," for r, label in pairs) + "\n    )"


def _ssrf_hosts(domains):
    parts = []
    for d in domains:
        parts.append(_q(d))
        parts.append(_q(f"*.{d}"))
    return "[" + ", ".join(parts) + "]"


def render(site):
    name = site["file"]
    site_id = site["site_id"]
    site_name = site["site_name"]
    class_name = "".join(part.capitalize() for part in site_id.split(".")) + "Spider"
    content_types = _content_types_repr(site["content_types"])
    section_urls = "[" + ", ".join(
        f"'{site['api']}/{rest}'" for rest, _ in site["content_types"]
    ) + "]"
    first_url = f"'{site['api']}/{site['content_types'][0][0]}?per_page=50&page=1'"
    ssrf = _ssrf_hosts(site["allowed_domains"])

    return f'''"""{site_name!r}（{site["source_category"]!r}）独立爬虫 —— 直连 WordPress REST API，采集全部栏目。

站点：{site["source_site"]!r}
数据源：{site["api"]!r}（WordPress REST API）

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

_API = {_q(site["api"])}
_PER_PAGE = 50

# (WP REST 资源名, 栏目中文名)
_CONTENT_TYPES = {content_types}

_SPACE_RE = re.compile(r"\\s+")


def _clean(value):
    return _SPACE_RE.sub(" ", str(value or "").replace("\\u00a0", " ")).strip()


def _field(post, name, sub="rendered"):
    """兼容 WP REST 中字段既可能是 dict（{{rendered: ...}}）也可能是纯字符串。"""
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


class {class_name}(scrapy.Spider):
    name = {_q(name)}
    site_id = {_q(site_id)}
    site_name = {_q(site_name)}
    site_type = {_q(site["site_type"])}
    language = {_q(site["language"])}
    source_title = {_q(site_name)}
    source_name = {_q(site_name)}
    source_category = {_q(site["source_category"])}
    source_site = {_q(site["source_site"])}
    allowed_domains = {site["allowed_domains"]!r}
    entry_url = {_q(site["source_site"])}
    section_urls = {section_urls}
    start_urls = [{first_url}]
    strict_news_only = False
    target_content_types = ("application/json",)
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'updates')
    detail_url_patterns = ()
    exclude_url_patterns = ()

    custom_settings = {{
        "LOG_LEVEL": "INFO",
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 0.5,
        "DOWNLOAD_TIMEOUT": 25,
        "RETRY_TIMES": 2,
        # 本站仅请求自身 WordPress REST 接口；在 fake-IP 代理环境下，域名解析到
        # 198.18.x.x / fd00:: 保留段，会被 SSRF 中间件误判，故显式放行本站域。
        "SSRF_ALLOWED_HOSTS": {ssrf},
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }}

    max_pages = 80

    async def start(self):
        # Scrapy 2.13+ 的入口是 async 生成器 ``start()``（旧版 ``start_requests`` 已不再被调用）。
        for rest_base, section in _CONTENT_TYPES:
            url = f"{{_API}}/{{rest_base}}?per_page={{_PER_PAGE}}&page=1"
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={{"rest_base": rest_base, "section": section, "page": 1}},
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
        next_url = f"{{_API}}/{{rest_base}}?per_page={{_PER_PAGE}}&page={{page + 1}}"
        yield scrapy.Request(
            next_url,
            callback=self.parse,
            meta={{"rest_base": rest_base, "section": section, "page": page + 1}},
        )

    def _build_item(self, post, section):
        title = _clean(html.unescape(_field(post, "title")))
        content_html = _field(post, "content")
        content = _strip_html(content_html)
        excerpt = _strip_html(_field(post, "excerpt"))
        link = _clean(_field(post, "link"))
        if not link:
            link = f"{site["source_site"].rstrip("/")}/?p={{post.get('id') or ''}}"
        if not title and not content:
            return None
        content_md = html_to_markdown(content_html, link)
        images = html_images(content_html, link)
        return {{
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
            "source_category": f"{{self.source_category}}·{{section}}",
            "domain": (urlparse(link).hostname or {_q(site_id)}).lower().removeprefix("www."),
        }}
'''


def main():
    SPIDERS_DIR.mkdir(parents=True, exist_ok=True)
    for site in SITES:
        path = SPIDERS_DIR / (site["file"] + ".py")
        path.write_text(render(site), encoding="utf-8")
        print("wrote", path)
    print(f"done: {len(SITES)} WordPress spiders")


if __name__ == "__main__":
    main()
