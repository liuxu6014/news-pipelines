"""生成全部独立 XPath 站点爬虫脚本（每个站点一个自包含文件）。

数据来源：docs/_sources_extracted.json（由 extract_sources.py 从
docs/张君正(1).xlsx 提取的站点，已排除大模型、知网/万方与电商/交易平台）。

设计原则（与用户要求一致）：
- 每个站点一个独立脚本，全部抓取/解析逻辑内联在单个文件里；
- 不继承任何项目级通用爬虫基类，只依赖 scrapy 与 Python 标准库；
- 解析全部通过 ``response.xpath(...)`` 完成，禁止 CSS 选择器；
- spider 名/文件名用「序号_域名」命名（如 001_163_com）。

本脚本只负责“生成”，生成后的蜘蛛需要按站点实际页面结构微调 XPath。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SOURCES_JSON = ROOT / "docs" / "_sources_extracted.json"
SITES_DIR = ROOT / "app" / "spiders"
MANIFEST_TXT = ROOT / "docs" / "site_spiders_manifest.txt"
MANIFEST_JSON = ROOT / "docs" / "site_spiders_manifest.json"

# 电商/交易/商城类平台，用户要求不采集。
ECOMMERCE_EXCLUDE_HOSTS = {
    "1688.com",
    "vipmro.com",
    "ckmro.com",
    "zkh360.com",
    "ymmfa.com",
    "51ima.com",
    "kegongyun.com",
}

# 非 .cn 后缀但内容为中文的站点，用于 language 标注。
_CHINESE_NON_CN_HOSTS = {
    "163.com",
    "autofg.com",
    "bbs.gkong.com",
    "bbs.gongkong.com",
    "china5e.com",
    "csdn.net",
    "gongkong.com",
    "ne21.com",
    "nengyuanjie.net",
    "tetraelc.com",
    "xny365.com",
    "youqichuyun.com",
    "zhihuiya.com",
    "zgznh.com",
}

# 列表页新闻链接常见关键词（用于站点级新闻 URL 识别）。
NEWS_URL_KEYWORDS = (
    "news", "press", "media", "insights", "stories", "updates",
    "xw", "zx", "tzgg", "zwgk", "gzyw", "gzdt", "xwzx",
)

# 政府站点的额外新闻列表 URL（按机构名匹配的站点级起点）。
GOV_EXTRA_START_URLS = {
    "财政部": [
        "http://www.mof.gov.cn/index.htm",
        "http://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/",
        "http://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/index.htm",
    ],
    "文化和旅游部": [
        "https://www.mct.gov.cn/whzx/whyw/",
        "https://www.mct.gov.cn/whzx/bnsj/",
        "https://www.mct.gov.cn/whzx/zsdw/",
    ],
    "国家金融监督管理总局": [
        "https://www.nfra.gov.cn/",
        "https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemPId=915&itemId=916",
    ],
    "国家机关事务管理局": [
        "https://www.ggj.gov.cn/xwzx/",
        "https://www.ggj.gov.cn/xwzx/ggjxw/",
        "https://www.ggj.gov.cn/xwzx/gzdt/",
    ],
    "江苏省国有资产监督管理委员会": [
        "https://jsgzw.jiangsu.gov.cn/col/col11717/index.html",
        "https://jsgzw.jiangsu.gov.cn/col/col61527/index.html",
        "https://jsgzw.jiangsu.gov.cn/col/col11779/index.html",
        "https://jsgzw.jiangsu.gov.cn/col/col11701/index.html",
    ],
    "福建省国有资产监督管理委员会": [
        "http://gzw.fujian.gov.cn/zwgk/gzdt/",
        "http://gzw.fujian.gov.cn/zwgk/gzyw/",
        "http://gzw.fujian.gov.cn/zwgk/gzdt/tpxw/",
    ],
    "广西壮族自治区国有资产监督管理委员会": [
        "http://gzw.gxzf.gov.cn/xwzx/",
        "http://gzw.gxzf.gov.cn/xwzx/gzyw/",
        "http://gzw.gxzf.gov.cn/xwzx/qydt/",
    ],
    "海南省国有资产监督管理委员会": [
        "https://gzw.hainan.gov.cn/zxdt_27423/",
        "https://gzw.hainan.gov.cn/zxdt_27423/zwdt/",
        "https://gzw.hainan.gov.cn/zxdt_27423/tpxw/",
        "https://gzw.hainan.gov.cn/zxdt_27423/gwygzyw/",
    ],
    "工业和信息化部": [
        "https://www.miit.gov.cn/xbymdz/sy/xbdh/xwfb/index.html",
        "https://www.miit.gov.cn/xwdt/gxdt/index.html",
    ],
    "民政部": [
        "https://www.mca.gov.cn/",
    ],
    "国家市场监督管理总局": [
        "https://www.samr.gov.cn/xw/",
        "https://www.samr.gov.cn/zw/",
    ],
    "中国气象局": [
        "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/",
    ],
    "国家粮食和物资储备局": [
        "https://www.lswz.gov.cn/html/xinwen/index.shtml",
    ],
    "国家能源局": [
        "https://www.nea.gov.cn/news/gd.htm",
        "https://www.nea.gov.cn/news/jwzdt.htm",
        "https://www.nea.gov.cn/news/pcjg.htm",
    ],
    "外交部": [
        "https://www.fmprc.gov.cn/zyxw/",
    ],
    "安徽省国有资产监督管理委员会": [
        "http://gzw.ah.gov.cn/ahgz/tzgg/index.html",
    ],
    "辽宁省国有资产监督管理委员会": [
        "https://gzw.ln.gov.cn/gzw/wzsy/tzgg/",
    ],
    "西藏自治区国有资产监督管理委员会": [
        "https://www.xizang.gov.cn/",
    ],
}

CATEGORY_SLUG = {
    "政策机构": "gov",
    "国外技术服务": "tech",
    "国际管道": "pipe",
    "新能源": "energy",
    "智能化": "smart",
    "机器人": "robot",
    "标准化管理": "standard",
    "泵机组": "pump",
    "电气": "elec",
    "知识产权与对外交流": "ip",
    "管道技术": "pipeline",
    "管道检测新技术有关专业网站": "inspect",
    "压缩机组相关": "compressor",
}

# 公开后缀（按长度降序，避免 gov.cn 被 cn 抢先匹配）。
_PUBLIC_SUFFIXES = sorted(
    [
        "gov.cn", "com.cn", "net.cn", "org.cn", "com.au", "co.jp",
        "com", "net", "org", "cn", "fr", "eu", "fi", "nl", "io", "co", "au", "jp",
    ],
    key=len,
    reverse=True,
)


def host_of(url):
    if "://" not in url:
        url = "http://" + url
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def registrable(host):
    host = host.lower().removeprefix("www.")
    for suffix in _PUBLIC_SUFFIXES:
        if host.endswith("." + suffix):
            prefix = host[: -len(suffix) - 1]
            return (prefix.rsplit(".", 1)[-1] + "." + suffix) if prefix else suffix
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


# ---- CSS -> XPath 转换（仅覆盖本项目 source_profiles 里出现的简单选择器）----

def _css_simple_to_xpath(part):
    part = part.strip()
    tag = "*"
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9_-]*)", part)
    if match and part[0] not in ".#[":
        tag = match.group(1)
    conds = []
    for m in re.finditer(
        r"\.([A-Za-z0-9_-]+)|#([A-Za-z0-9_-]+)|\[([A-Za-z0-9_:@-]+)\s*=\s*['\"]([^'\"]*)['\"]\]",
        part,
    ):
        cls, id_, attr, val = m.groups()
        if cls is not None:
            conds.append(f"contains(concat(' ',normalize-space(@class),' '),' {cls} ')")
        elif id_ is not None:
            conds.append(f"@id='{id_}'")
        elif attr is not None:
            conds.append(f"@{attr}='{val}'")
    if not conds:
        return tag
    return f"{tag}[{' and '.join(conds)}]"


def css_to_xpath(selector):
    selector = selector.strip()
    text_axis = selector.endswith("::text")
    selector = selector.replace("::text", "")
    fragments = []
    for part in re.split(r"\s+|\s*>\s*", selector):
        if not part:
            continue
        first_child = part.endswith(":first-child")
        part = re.sub(r":(first|last)-child\b", "", part)
        nth = re.search(r":nth-child\((\d+)\)", part)
        part = re.sub(r":nth-child\(\d+\)", "", part)
        fragment = _css_simple_to_xpath(part)
        if nth:
            fragment += f"[{nth.group(1)}]"
        elif first_child:
            fragment += "[1]"
        fragments.append(fragment)
    xpath = "//" + "//".join(fragments)
    if text_axis:
        xpath += "//text()"
    return xpath


def _self_test_css():
    cases = {
        "article": "//article",
        ".article-content": "//*[contains(concat(' ',normalize-space(@class),' '),' article-content ')]",
        "#ozoom": "//*[@id='ozoom']",
        "table.articlebox": "//table[contains(concat(' ',normalize-space(@class),' '),' articlebox ')]",
        "[itemprop='articleBody']": "//*[@itemprop='articleBody']",
        ".fywidth.fybjq.fyxwbjq": (
            "//*[contains(concat(' ',normalize-space(@class),' '),' fywidth ') "
            "and contains(concat(' ',normalize-space(@class),' '),' fybjq ') "
            "and contains(concat(' ',normalize-space(@class),' '),' fyxwbjq ')]"
        ),
        ".newsletter-contents li": (
            "//*[contains(concat(' ',normalize-space(@class),' '),' newsletter-contents ')]//li"
        ),
        ".time::text": "//*[contains(concat(' ',normalize-space(@class),' '),' time ')]//text()",
    }
    for selector, expected in cases.items():
        got = css_to_xpath(selector)
        assert got == expected, f"CSS->XPath 失败: {selector!r} -> {got!r} != {expected!r}"


# ---- 行业站点画像 ----
# 迁移后站点级正文/日期选择器已内联进各独立 spider，不再维护集中画像注册表。
# 该生成器只产出骨架脚本，具体 XPath 需按站点实际页面结构微调（见脚本头部说明）。

def _load_industry_profiles():
    return {}


def parse_label(label):
    if ":" in label:
        category, _, name = label.partition(":")
        return category.strip(), name.strip()
    return label.strip(), ""


def class_name_for(host):
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", host) if p]
    return "XPath" + "".join(p.capitalize() for p in parts) + "Spider"


def spider_name_for(host, seq):
    return f"{seq:03d}_{re.sub(r'[^a-z0-9]+', '_', host.lower()).strip('_')}"


def language_for(host):
    if host.endswith((".cn", ".com.cn", ".net.cn", ".org.cn")):
        return "zh-CN"
    if host in _CHINESE_NON_CN_HOSTS:
        return "zh-CN"
    return "en"


# ---- 独立蜘蛛模板 ----

_TEMPLATE = '''"""<<SOURCE_NAME>>（<<CATEGORY>>）独立 XPath 爬虫。

站点：<<SITE_URL>>
本脚本自包含全部抓取/解析逻辑，仅依赖 scrapy 与 app.html_markdown（HTML→Markdown
转换），不继承任何项目级通用爬虫基类。解析全部通过 ``response.xpath(...)`` 完成。

XPath 选择器为初始值，需按站点实际页面结构微调后再投入长期采集。
"""
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import scrapy

from app.html_markdown import html_images, html_to_markdown

_SPACE_RE = re.compile(r"\\s+")
_BINARY_EXT = re.compile(
    r"\\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|jpg|jpeg|png|gif|mp4|mp3|wav)(\\?.*)?$",
    re.I,
)
_DATE_RE = re.compile(
    r"(20\\d{2})[-/.年](\\d{1,2})[-/.月](\\d{1,2})日?(?:\\s+(\\d{1,2}):(\\d{2})(?::(\\d{2}))?)?"
)
_URL_DATE = re.compile(r"20\\d{2}[-_/]?\\d{0,2}[-_/]?\\d{0,2}")

# ---- 站点 XPath 选择器（按需微调）----
LIST_ITEM_XPATH = <<LIST_ITEM_XPATH>>
LIST_TITLE_XPATH = ".//a/text()"
LIST_LINK_XPATH = ".//a/@href"
DETAIL_TITLE_XPATH = <<DETAIL_TITLE_XPATH>>
DETAIL_CONTENT_XPATH = <<DETAIL_CONTENT_XPATH>>
DETAIL_DATE_XPATH = <<DETAIL_DATE_XPATH>>
DETAIL_PATTERNS = <<DETAIL_PATTERNS>>

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
    return _SPACE_RE.sub(" ", str(value or "").replace("\\u00a0", " ")).strip()


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


class <<CLASS_NAME>>(scrapy.Spider):
    name = <<SPIDER_NAME>>
    site_id = <<SITE_ID>>
    site_name = <<SOURCE_NAME>>
    site_type = <<SITE_TYPE>>
    language = <<LANGUAGE>>
    source_title = <<SOURCE_NAME>>
    source_name = <<SOURCE_NAME>>
    source_category = <<CATEGORY>>
    source_site = <<SITE_URL>>
    allowed_domains = <<ALLOWED_DOMAINS>>
    entry_url = <<ENTRY_URL>>
    section_urls = <<START_URLS>>
    start_urls = <<START_URLS>>
    strict_news_only = True
    target_content_types = ("text/html",)
    news_url_keywords = <<NEWS_URL_KEYWORDS>>
    detail_url_patterns = DETAIL_PATTERNS
    exclude_url_patterns = (_BINARY_EXT.pattern,)

    custom_settings = {
        "SSRF_ALLOWED_HOSTS": <<SSRF_ALLOWED_HOSTS>>,
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

    max_pages = <<MAX_PAGES>>
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
        if not content or len(content) < <<MIN_CONTENT_LENGTH>>:
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
        if not re.search(r"\\.(?:htm|html|shtml)$", path):
            return False
        return bool(_URL_DATE.search(url) or re.search(r"(?:content|art)_?\\d+", path, re.I))

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
            r"(?:发布时间|发布日期|日期|时间)\\s*[:：]?\\s*"
            r"(20\\d{2}[-/.年]\\d{1,2}[-/.月]\\d{1,2}日?(?:\\s+\\d{1,2}:\\d{2})?)",
            response.text[:30000],
        ):
            normalized = _normalize_date(match.group(1))
            if normalized:
                return normalized
        return ""
'''


def build_site(site, profile_by_host, seq):
    host = site["host"]
    url = site["url"]
    category, name = parse_label(site["label"])

    source_category = category
    source_name = name or host
    slug = CATEGORY_SLUG.get(category, "other")

    start_urls = [url]
    detail_patterns = ()
    detail_content_xpath = ()
    detail_date_xpath = ()
    detail_title_xpath = ("//h1//text()",)
    list_item_xpath = ""
    enriched = False

    profile = profile_by_host.get(host)
    if profile is not None:
        enriched = True
        source_name = profile.name
        start_urls = list(dict.fromkeys(profile.section_urls)) or start_urls
        detail_patterns = tuple(profile.detail_patterns)
        detail_content_xpath = tuple(css_to_xpath(s) for s in profile.content_selectors)
        detail_date_xpath = tuple(css_to_xpath(s) for s in profile.date_selectors)
        title_xpaths = [css_to_xpath(s) for s in profile.title_selectors]
        title_xpaths.append("//h1//text()")
        # 去重且保持顺序
        detail_title_xpath = tuple(dict.fromkeys(title_xpaths))

    if category == "政策机构" and name in GOV_EXTRA_START_URLS:
        for extra in GOV_EXTRA_START_URLS[name]:
            if extra not in start_urls:
                start_urls.append(extra)

    allowed_domains = sorted({registrable(host_of(u)) for u in start_urls if host_of(u)})

    return {
        "host": host,
        "url": url,
        "category": source_category,
        "source_name": source_name,
        "slug": slug,
        "spider_name": spider_name_for(host, seq),
        "class_name": class_name_for(host),
        "site_id": host,
        "site_type": slug,
        "language": language_for(host),
        "entry_url": start_urls[0],
        "news_url_keywords": NEWS_URL_KEYWORDS,
        "start_urls": start_urls,
        "allowed_domains": allowed_domains,
        "ssrf_allowed_hosts": [d for domain in allowed_domains for d in (domain, "*." + domain)],
        "list_item_xpath": list_item_xpath,
        "detail_title_xpath": detail_title_xpath,
        "detail_content_xpath": detail_content_xpath,
        "detail_date_xpath": detail_date_xpath,
        "detail_patterns": detail_patterns,
        "enriched": enriched,
    }


def render(site_cfg):
    def rep(value):
        return repr(value)

    text = _TEMPLATE
    for token, value in {
        "<<SOURCE_NAME>>": rep(site_cfg["source_name"]),
        "<<CATEGORY>>": rep(site_cfg["category"]),
        "<<SITE_URL>>": rep(site_cfg["url"]),
        "<<CLASS_NAME>>": site_cfg["class_name"],
        "<<SPIDER_NAME>>": rep(site_cfg["spider_name"]),
        "<<SITE_ID>>": rep(site_cfg["site_id"]),
        "<<SITE_TYPE>>": rep(site_cfg["site_type"]),
        "<<LANGUAGE>>": rep(site_cfg["language"]),
        "<<ENTRY_URL>>": rep(site_cfg["entry_url"]),
        "<<NEWS_URL_KEYWORDS>>": rep(site_cfg["news_url_keywords"]),
        "<<ALLOWED_DOMAINS>>": rep(site_cfg["allowed_domains"]),
        "<<SSRF_ALLOWED_HOSTS>>": rep(site_cfg["ssrf_allowed_hosts"]),
        "<<START_URLS>>": rep(site_cfg["start_urls"]),
        "<<LIST_ITEM_XPATH>>": rep(site_cfg["list_item_xpath"]),
        "<<DETAIL_TITLE_XPATH>>": rep(site_cfg["detail_title_xpath"]),
        "<<DETAIL_CONTENT_XPATH>>": rep(site_cfg["detail_content_xpath"]),
        "<<DETAIL_DATE_XPATH>>": rep(site_cfg["detail_date_xpath"]),
        "<<DETAIL_PATTERNS>>": rep(site_cfg["detail_patterns"]),
        "<<MAX_PAGES>>": "80",
        "<<MIN_CONTENT_LENGTH>>": "80",
    }.items():
        text = text.replace(token, value)
    return text


def main():
    _self_test_css()
    if not SOURCES_JSON.exists():
        raise SystemExit(f"缺少 {SOURCES_JSON}，请先运行 extract_sources.py 生成。")

    sites = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    profile_by_host = _load_industry_profiles()

    SITES_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    written = 0
    seq = 0
    for site in sites:
        host = (site.get("host") or "").lower().removeprefix("www.")
        if host in ECOMMERCE_EXCLUDE_HOSTS:
            continue
        seq += 1
        cfg = build_site(site, profile_by_host, seq)
        target = SITES_DIR / (cfg["spider_name"] + ".py")
        target.write_text(render(cfg), encoding="utf-8")
        written += 1

        manifest.append(
            {
                "spider": cfg["spider_name"],
                "file": str(target.relative_to(ROOT)).replace("\\", "/"),
                "source_name": cfg["source_name"],
                "category": cfg["category"],
                "host": cfg["host"],
                "start_urls": cfg["start_urls"],
                "enriched": cfg["enriched"],
            }
        )

    manifest.sort(key=lambda row: (row["category"], row["spider"]))
    MANIFEST_JSON.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# 独立 XPath 站点爬虫清单（{written} 个）\n"]
    for row in manifest:
        flag = "profile" if row["enriched"] else ""
        lines.append(
            f"{row['spider']}\t{row['source_name']}\t{row['category']}\t{row['host']}\t{len(row['start_urls'])}\t{flag}"
        )
    MANIFEST_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"generated {written} spiders under app/spiders/")
    print(f"manifest: {MANIFEST_TXT}")


if __name__ == "__main__":
    main()
