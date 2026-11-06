"""生成「sitemap.xml 直连」的独立站点爬虫（平铺到 app/spiders/）。

每个生成的脚本自包含全部逻辑，仅依赖 scrapy + 标准库，不继承任何项目级基类。
遵循 scrapy-spider skill 约定：

- 入口用 ``async def start()``（本项目 Scrapy 2.13+ 已不再调用 ``start_requests``）。
- 以 sitemap 为 URL 清单接口，逐条枚举内容型 URL，按 URL 路径归属栏目，写入
  ``source_category``（如 ``国际管道·故事``），采集「全部栏目」。
- 详情页是服务端渲染 HTML，用 XPath 提取标题 / 日期 / 正文。日期按
  meta / time / ``*[@class~='date']`` 结构化元素优先，兜底按 URL 内嵌日期或正文
  首个日期文本；无正文 / 非内容页自动跳过。
- ``custom_settings["SSRF_ALLOWED_HOSTS"]`` 放行本站域（规避 fake-IP 代理下 SSRF
  误判）。

用法：``uv run python tools/generate_sitemap_spiders.py``
"""
from __future__ import annotations

import re
from pathlib import Path

SPIDERS_DIR = Path(__file__).resolve().parents[1] / "app" / "spiders"


def _q(value):
    return repr(str(value))


def _list_repr(values):
    return "[" + ", ".join(_q(v) for v in values) + "]"


def _rules_repr(rules):
    # rules: [(regex, label), ...]
    return "[" + ", ".join(f"({_q(r)}, {_q(label)})" for r, label in rules) + "]"


def _ssrf_hosts(domains):
    parts = []
    for d in domains:
        parts.append(_q(d))
        parts.append(_q(f"*.{d}"))
    return "[" + ", ".join(parts) + "]"


# (文件名, 配置)
# detail_res: 命中任一才算内容详情页；exclude_res: 命中任一即排除（列表/导航/附件）。
# section_rules: [(URL 正则, 栏目名)]，首个命中者写入 source_category。
# date_xpaths_extra / content_xpaths_extra: 站点专属 XPath，前置到通用选择器之前。
SITES = [
    dict(
        file="023_enbridge_com",
        site_id="enbridge.com",
        site_name="Enbridge Inc",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.enbridge.com/",
        allowed_domains=["enbridge.com"],
        sitemap_urls=["https://www.enbridge.com/sitemap-enbridge.xml"],
        detail_res=[
            r"/stories/20\d{2}/[a-z0-9-]+/[a-z0-9-]+$",
            r"/enbridge-viewpoints/[a-z0-9-]+$",
            r"/media-center/[a-z0-9-]+/[a-z0-9-]+$",
            r"/media-statements/[a-z0-9-]+$",
            r"/line-5-newsroom/[a-z0-9-]+$",
            r"/project-updates$",
        ],
        exclude_res=[r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip|mp4)(\?|$)"],
        section_rules=[
            (r"/stories/", "故事"),
            (r"/enbridge-viewpoints/", "观点"),
            (r"/media-statements/", "媒体声明"),
            (r"/media-center/", "媒体中心"),
            (r"/line-5-newsroom/", "Line 5 新闻"),
            (r"/project-updates", "项目进展"),
        ],
        date_xpaths_extra=["//div[contains(@class,'story-date-new')]//text()"],
        content_xpaths_extra=[
            "//div[contains(@class,'story-content-section-new')]",
            "//div[contains(@class,'story-subtitle-new')]",
        ],
    ),
    dict(
        file="033_oneok_com",
        site_id="oneok.com",
        site_name="ONEOK",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.oneok.com/",
        allowed_domains=["oneok.com"],
        sitemap_urls=["https://www.oneok.com/sitemap.xml"],
        detail_res=[r"/Newsroom/[a-z0-9-]+/[a-z0-9-]+$"],
        exclude_res=[r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)"],
        section_rules=[
            (r"/company-news/", "公司新闻"),
            (r"/press-releases/", "新闻稿"),
            (r"/stories/", "故事"),
            (r"/earnings/", "财报"),
            (r"/leadership-perspectives/", "领导视角"),
            (r"/our-people/", "员工故事"),
            (r"/community/", "社区"),
            (r"/projects-and-operations/", "项目与运营"),
            (r"/Newsroom/", "新闻中心"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="035_tcenergy_com",
        site_id="tcenergy.com",
        site_name="TC Energy Corp",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.tcenergy.com/",
        allowed_domains=["tcenergy.com"],
        sitemap_urls=["https://www.tcenergy.com/sitemap.xml"],
        detail_res=[
            r"/announcements/20\d{2}/",
            r"/newsroom/",
            r"/news-and-events/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/newsroom/?$",
            r"/newsroom/[a-z0-9-]+/?$",
            r"/announcements/?$",
            r"/announcements/20\d{2}/?$",
        ],
        section_rules=[
            (r"/announcements/", "公告"),
            (r"/newsroom/statements", "声明"),
            (r"/newsroom/", "新闻室"),
            (r"/news-and-events/", "新闻与活动"),
        ],
        date_xpaths_extra=["//*[contains(@class,'date')]//text()"],
    ),
    dict(
        file="032_nationalgas_com",
        site_id="nationalgas.com",
        site_name="National Grid Gas plc",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.nationalgas.com/",
        allowed_domains=["nationalgas.com"],
        sitemap_urls=["https://nationalgas.com/sitemap.xml"],
        detail_res=[
            r"/media/news/",
            r"/media/publications/",
            r"/ngm-latest-news",
            r"/operational-news",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/media/news/?$",
            r"/media/publications/?$",
        ],
        section_rules=[
            (r"/media/news/", "新闻"),
            (r"/media/publications/", "出版物"),
            (r"/ngm-latest-news", "NGM 新闻"),
            (r"/operational-news", "运营新闻"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="016_statsgroup_com",
        site_id="statsgroup.com",
        site_name="STATS Group",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="http://statsgroup.com",
        allowed_domains=["statsgroup.com"],
        sitemap_urls=["https://statsgroup.com/sitemap.xml"],
        detail_res=[
            r"/news/",
            r"/resources/case-studies/",
            r"/resources/video/",
            r"/events/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/news/?$",
            r"/resources/?$",
            r"/events/?$",
        ],
        section_rules=[
            (r"/news/", "新闻"),
            (r"/case-studies/", "案例"),
            (r"/video/", "视频"),
            (r"/events/", "活动"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="026_natrangroupe_com",
        site_id="natrangroupe.com",
        site_name="GRTgaz",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.natrangroupe.com/",
        allowed_domains=["natrangroupe.com"],
        sitemap_urls=["https://natrangroupe.com/sitemap.xml"],
        detail_res=[
            r"/medias/",
            r"/actualites/",
            r"/communiques",
            r"/article/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/medias/?$",
            r"/actualites/?$",
        ],
        section_rules=[
            (r"/news/", "新闻"),
            (r"/actualites/", "动态"),
            (r"/communiques", "新闻稿"),
            (r"/article/", "文章"),
            (r"/medias/", "媒体"),
        ],
        content_xpaths_extra=[
            "//div[contains(@class,'field--name-body')]",
            "//div[contains(@class,'format-texte-libre')]",
            "//div[contains(@class,'field__item')]",
        ],
        allow_body_date=True,
    ),
    dict(
        file="020_worley_com",
        site_id="worley.com",
        site_name="Worley Group",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="https://www.worley.com/",
        allowed_domains=["worley.com"],
        sitemap_urls=["https://worley.com/sitemap.xml"],
        detail_res=[
            r"/en/insights/",
            r"/case-studies/",
            r"/our-news/",
            r"/our-thinking/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/en/insights/?$",
            r"/insights/?$",
        ],
        section_rules=[
            (r"/our-news/", "新闻"),
            (r"/our-thinking/", "思考"),
            (r"/case-studies/", "案例"),
            (r"/en/insights/", "洞察"),
        ],
        date_xpaths_extra=["//p[contains(@class,'wp-hero--label')]//text()"],
    ),
    dict(
        file="125_bakerhughes_com",
        site_id="bakerhughes.com",
        site_name="bakerhughes.com",
        site_type="robot",
        language="en",
        source_category="机器人",
        source_site="https://www.bakerhughes.com/cn/waygate-technologies/robotic-inspection",
        allowed_domains=["bakerhughes.com"],
        sitemap_urls=["https://bakerhughes.com/sitemap.xml"],
        detail_res=[
            r"/company/news/",
            r"/company/stories/",
            r"/waygate-technologies/news/",
            r"/waygate-technologies/blog/",
            r"/cordant/blog/",
            r"/panametrics/success-stories/",
            r"/panametrics/blog/",
            r"/druck/news/",
            r"/bently-nevada/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/company/news/?$",
            r"/company/stories/?$",
            r"/waygate-technologies/news/?$",
            r"/waygate-technologies/blog/?$",
            r"/cordant/blog/?$",
        ],
        section_rules=[
            (r"/company/news/", "公司新闻"),
            (r"/company/stories/", "故事"),
            (r"/waygate-technologies/blog/", "Waygate 博客"),
            (r"/waygate-technologies/news/", "Waygate 新闻"),
            (r"/cordant/blog/", "Cordant 博客"),
            (r"/panametrics/", "Panametrics"),
            (r"/druck/", "Druck"),
            (r"/bently-nevada/", "Bently Nevada"),
            (r"/blog/", "博客"),
        ],
        date_xpaths_extra=["//p[contains(@class,'publish-date')]//text()"],
    ),
    dict(
        file="018_technipfmc_com",
        site_id="technipfmc.com",
        site_name="TechnipFMC",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="https://www.technipfmc.com/",
        allowed_domains=["technipfmc.com"],
        sitemap_urls=["https://www.technipfmc.com/xmlsitemap"],
        detail_res=[
            r"/en/media/news/",
            r"/en/media/press-releases/",
            r"/en/investors/financial-news-releases/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/en/media/?$",
            r"/en/media/news/?$",
            r"/en/investors/?$",
        ],
        section_rules=[
            (r"/financial-news-releases/", "财务新闻稿"),
            (r"/press-releases/", "新闻稿"),
            (r"/media/news/", "新闻"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="145_rosen_group_com",
        site_id="rosen-group.com",
        site_name="rosen-group.com",
        site_type="inspect",
        language="en",
        source_category="管道检测新技术有关专业网站",
        source_site="https://www.rosen-group.com/en",
        allowed_domains=["rosen-group.com"],
        sitemap_urls=["https://rosen-group.com/sitemap.xml"],
        detail_res=[
            r"/en/media-and-events/",
            r"/en/expertise/.+/blog/",
            r"/en/expertise/.+/news/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/en/media-and-events/?$",
        ],
        section_rules=[
            (r"/blog/", "博客"),
            (r"/news/", "新闻"),
            (r"/media-and-events/", "媒体与活动"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="003_cbmm_com",
        site_id="cbmm.com",
        site_name="CBMM Technology Suisse SA",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="https://cbmm.com/",
        allowed_domains=["cbmm.com"],
        sitemap_urls=["https://cbmm.com/sitemap.xml"],
        detail_res=[
            r"/midias/",
            r"/media-center/",
            r"/noticias/",
            r"/releases/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/midias/?$",
            r"/media-center/?$",
        ],
        section_rules=[
            (r"/noticias/", "新闻"),
            (r"/releases/", "新闻稿"),
            (r"/midias/", "媒体"),
            (r"/media-center/", "媒体中心"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="029_gasunie_nl",
        site_id="gasunie.nl",
        site_name="Gasunie",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.gasunie.nl/en",
        allowed_domains=["gasunie.nl"],
        sitemap_urls=["https://www.gasunie.nl/robots.txt/sitemap?lang=en_GB"],
        detail_res=[
            r"/en/news/[a-z0-9-]+$",
            r"/en/newsletter/[a-z0-9-]+/[a-z0-9-]+$",
            r"/en/expertise/[a-z0-9-]+/[a-z0-9-]+$",
        ],
        exclude_res=[r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)"],
        section_rules=[
            (r"/en/newsletter/", "新闻通讯"),
            (r"/en/news/", "新闻"),
            (r"/en/expertise/", "专家见解"),
        ],
        date_xpaths_extra=["//*[contains(@class,'meta-item-date')]//text()"],
        allow_body_date=True,
    ),
    dict(
        file="150_ndt_global_com",
        site_id="ndt-global.com",
        site_name="NDT Global",
        site_type="inspect",
        language="en",
        source_category="管道检测新技术有关专业网站",
        source_site="https://www.ndt-global.com/",
        allowed_domains=["ndt-global.com"],
        sitemap_urls=["https://www.ndt-global.com/sitemap.xml"],
        detail_res=[
            r"/resources/blog/[a-z0-9-]+/$",
            r"/resources/news/[a-z0-9-]+/$",
            r"/resources/case-study/[a-z0-9-]+/$",
            r"/resources/white-paper/[a-z0-9-]+/$",
            r"/resources/event/[a-z0-9-]+/$",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/(inline-inspection-ultrasonic-technology|inline-inspection-magnetic-flux-leakage|integrity-management|subsea-and-robotics)/?$",
        ],
        section_rules=[
            (r"/resources/news/", "新闻"),
            (r"/resources/blog/", "博客"),
            (r"/resources/case-study/", "案例研究"),
            (r"/resources/white-paper/", "白皮书"),
            (r"/resources/event/", "活动"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="146_tdwilliamson_com",
        site_id="tdwilliamson.com",
        site_name="T.D. Williamson",
        site_type="inspect",
        language="en",
        source_category="管道检测新技术有关专业网站",
        source_site="https://www.tdwilliamson.com/",
        allowed_domains=["tdwilliamson.com"],
        sitemap_urls=["https://www.tdwilliamson.com/sitemap.xml"],
        detail_res=[
            r"/resources/news/[a-z0-9-]+$",
            r"/resources/case-studies/[a-z0-9-]+$",
            r"/resources/papers/[a-z0-9-]+$",
            r"/resources/webinars/[a-z0-9-]+$",
        ],
        exclude_res=[r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip|mp4)(\?|$)"],
        section_rules=[
            (r"/resources/news/", "新闻"),
            (r"/resources/case-studies/", "案例研究"),
            (r"/resources/papers/", "技术论文"),
            (r"/resources/webinars/", "网络研讨会"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="021_apa_com_au",
        site_id="apa.com.au",
        site_name="APA Group",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.apa.com.au/",
        allowed_domains=["apa.com.au"],
        sitemap_urls=["https://www.apa.com.au/sitemap.xml"],
        detail_res=[
            r"/news/asx-and-media-releases/[a-z0-9-]+$",
            r"/news/transmission-industry-insights/[a-z0-9-]+$",
            r"/news/case-studies/[a-z0-9-]+$",
        ],
        exclude_res=[r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip|mp4)(\?|$)"],
        section_rules=[
            (r"/news/transmission-industry-insights/", "行业洞察"),
            (r"/news/case-studies/", "案例研究"),
            (r"/news/asx-and-media-releases/", "ASX 与媒体发布"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="031_kindermorgan_com",
        site_id="kindermorgan.com",
        site_name="Kinder Morgan Inc",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.kindermorgan.com/",
        allowed_domains=["kindermorgan.com"],
        sitemap_urls=["https://www.kindermorgan.com/sitemap.xml"],
        detail_res=[
            r"/Pages/Energy-Delivered/[^/]+$",
            r"/Operations/KM-Treating/News/[^/]+$",
            r"/Energy-Realities/[^/]+$",
        ],
        exclude_res=[r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip|mp4)(\?|$)"],
        section_rules=[
            (r"/Energy-Delivered/", "Energy Delivered 故事"),
            (r"/KM-Treating/News/", "KM-Treating 新闻"),
            (r"/Energy-Realities/", "能源现实"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="024_fluxys_com",
        site_id="fluxys.com",
        site_name="Fluxys Belgium SA",
        site_type="pipe",
        language="en",
        source_category="国际管道",
        source_site="https://www.fluxys.com/en",
        allowed_domains=["fluxys.com"],
        sitemap_urls=["https://www.fluxys.com/sitemap.xml"],
        detail_res=[
            r"/en/press-releases/[^/]+/\d{4}/[^/]+$",
            r"/en/news/[^/]+/\d{4}/[^/]+$",
            r"/en/news/[^/]+/[^/]+$",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip|mp4)(\?|$)",
            r"/en/news/[^/]+/\d{4}/?$",
            r"/en/press-releases/[^/]+/\d{4}/?$",
        ],
        section_rules=[
            (r"/en/press-releases/", "新闻稿"),
            (r"/en/news/fluxys-hydrogen/", "Fluxys 氢能"),
            (r"/en/news/fluxys-lng/", "Fluxys LNG"),
            (r"/en/news/fluxys-belgium/", "Fluxys 比利时"),
            (r"/en/news/fluxys-deutschland/", "Fluxys 德国"),
            (r"/en/news/fluxys-tenp/", "Fluxys TENP"),
            (r"/en/news/fluxys-group/", "Fluxys 集团"),
            (r"/en/news/fluxswiss/", "FluxSwiss"),
            (r"/en/news/interconnector/", "Interconnector"),
            (r"/en/news/dunkerque-lng/", "Dunkerque LNG"),
            (r"/en/news/cross-site-news/", "跨站新闻"),
            (r"/en/news/", "新闻"),
        ],
        allow_body_date=True,
    ),
    dict(
        file="015_rmg_com",
        site_id="rmg.com",
        site_name="RMG Messtechnik GmbH",
        site_type="tech",
        language="en",
        source_category="国外技术服务",
        source_site="https://www.rmg.com/",
        allowed_domains=["rmg.com"],
        sitemap_urls=["https://rmg.com/sitemap.xml"],
        detail_res=[
            r"/publications/",
            r"/publikationen/",
            r"/veroeffentlichungen/",
            r"/publikace/",
            r"/pubblicazioni/",
            r"/publikacje/",
            r"/publicacoes/",
        ],
        exclude_res=[
            r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)(\?|$)",
            r"/publications/?$",
            r"/publikationen/?$",
        ],
        section_rules=[
            (r"/publications/", "出版物"),
            (r"/publikationen/", "出版物"),
            (r"/veroeffentlichungen/", "出版物"),
            (r"/publikace/", "出版物"),
            (r"/pubblicazioni/", "出版物"),
            (r"/publikacje/", "出版物"),
        ],
        allow_body_date=True,
    ),
]


TEMPLATE = '''"""{site_name}（{source_category}）独立爬虫 —— 直连 sitemap.xml，采集全部栏目。

站点：{source_site}
数据源：sitemap.xml（站点自身的 URL 清单接口）

「全部栏目」：从 sitemap 枚举全部内容型 URL，按 URL 路径归属栏目，写入
``source_category``（如 ``{source_category}·栏目``）。详情页是服务端渲染 HTML，用
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

_SITEMAP_URLS = {sitemap_urls}

# 命中任一才算内容详情页（为空 = 不额外过滤）
_DETAIL_URL_RES = {detail_res}
# 命中任一即排除（列表页 / 导航 / 附件）
_EXCLUDE_URL_RES = {exclude_res}
# (URL 正则, 栏目名)：首个命中者写入 source_category
_SECTION_RULES = {section_rules}

# 站点专属选择器，前置到通用选择器之前
_DATE_XPATHS = {date_xpaths}
_CONTENT_XPATHS = {content_xpaths}

_ALLOW_BODY_DATE = {allow_body_date}

_SPACE_RE = re.compile(r"\\s+")
_DATE_TEXT_RE = re.compile(
    r"(?:(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?\\s+"
    r"\\d{1,2}(?:st|nd|rd|th)?,?\\s+20\\d{2}|"
    r"\\d{1,2}\\s+(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\\.?\\s+20\\d{2}|20\\d{2}[-/.]\\d{1,2}[-/.]\\d{1,2})"
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
    return _SPACE_RE.sub(" ", str(value or "").replace("\\u00a0", " ")).strip()


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
    text = re.sub(r"\\b(st|nd|rd|th)\\b", "", text, flags=re.I)
    text = re.sub(r"([A-Za-z]{3,9})\\.", r"\\1", text)
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
    match = re.search(r"(20\\d{2})[-/](\\d{1,2})[-/](\\d{1,2})", url)
    if match:
        try:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        except ValueError:
            pass
    match = re.search(r"(?:^|[/_-])(20\\d{2})(\\d{2})(\\d{2})(?:[/_-]|$)", url)
    if match:
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    match = re.search(r"(?:^|[/_-])(2\\d)(\\d{2})(\\d{2})(?:[/_-]|$)", url)
    if match:
        y, m, d = 2000 + int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    match = re.search(r"/(20\\d{2})/(\\d{1,2})/", url)
    if match:
        try:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-01"
        except ValueError:
            pass
    return ""


class {class_name}(scrapy.Spider):
    name = {name}
    site_id = {site_id}
    site_name = {site_name}
    site_type = {site_type}
    language = {language}
    source_title = {site_name}
    source_name = {site_name}
    source_category = {source_category}
    source_site = {source_site}
    allowed_domains = {allowed_domains}
    entry_url = {source_site}
    section_urls = {sitemap_urls}
    start_urls = {sitemap_urls}
    strict_news_only = False
    target_content_types = ("text/xml", "application/xml", "application/rss+xml")
    news_url_keywords = ('news', 'press', 'media', 'insights', 'stories', 'blog', 'release', 'article', 'announcement', 'event', 'publication')
    detail_url_patterns = {detail_res}
    exclude_url_patterns = {exclude_res}

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
        "SSRF_ALLOWED_HOSTS": {ssrf},
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
            "domain": (urlparse(url).hostname or {site_id}).lower().removeprefix("www."),
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
'''


def render(site):
    out = TEMPLATE
    parts = [re.sub(r"[^A-Za-z0-9]", "", p) for p in re.split(r"[.\-_]", site["site_id"]) if p]
    class_name = "".join(p.capitalize() for p in parts) + "Spider"
    out = out.replace("{class_name}", class_name)
    for key in ("site_id", "site_name", "site_type", "language", "source_category", "source_site", "name", "file"):
        val = site["file"] if key == "name" else site[key]
        out = out.replace(f"{{{key}}}", _q(val))
    out = out.replace("{allowed_domains}", site["allowed_domains"].__repr__())
    out = out.replace("{sitemap_urls}", _list_repr(site["sitemap_urls"]))
    out = out.replace("{detail_res}", _list_repr(site["detail_res"]))
    out = out.replace("{exclude_res}", _list_repr(site["exclude_res"]))
    out = out.replace("{section_rules}", _rules_repr(site["section_rules"]))
    out = out.replace("{date_xpaths}", _list_repr(site.get("date_xpaths_extra", [])))
    out = out.replace("{content_xpaths}", _list_repr(site.get("content_xpaths_extra", [])))
    out = out.replace("{allow_body_date}", repr(site.get("allow_body_date", False)))
    out = out.replace("{ssrf}", _ssrf_hosts(site["allowed_domains"]))
    return out


def main():
    SPIDERS_DIR.mkdir(parents=True, exist_ok=True)
    for site in SITES:
        path = SPIDERS_DIR / (site["file"] + ".py")
        path.write_text(render(site), encoding="utf-8")
        print("wrote", path)
    print(f"done: {len(SITES)} sitemap spiders")


if __name__ == "__main__":
    main()
