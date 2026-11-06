# 站点接口（API）发现进度

逐站排查每个独立爬虫站点背后是否有真实的 JSON/XML 接口，据此决定「直连接口」还是「XPath 解析列表页」。

## 探测方法

- 工具：`tools/probe_site_apis.py`（读取 `docs/site_spiders_manifest.json`，抓取 entry_url + 常见 sitemap 路径，扫描 HTML/JS 里的 API/JSON/ajax/getJSON 信号）。
- 完整逐站信号：`run_reports/site_api_probe.json`（运行产物，不入库）。

## 关键结论（重要）

1. **政府站的 `pushInfoJsonpCallBack` 是共享的「国务院要闻」中心 feed，不是站点自身新闻。**
   实际接口是 `https://www.gov.cn/pushinfo/v150203/pushinfo.jsonp`（JSONP，返回 `author=中国政府网`、链接到 `www.gov.cn/zhengce/...`）。大量政府站首页只是内嵌这个中央 widget，其**自身**新闻列表仍是服务端渲染 HTML。
2. **绝大多数站点是服务端渲染 HTML，没有公开的 JSON 新闻接口** —— 这类站点维持现有 XPath 列表/详情解析即为正确做法，无需也找不到接口。
3. **真正有接口的主要是国外企业站**（WordPress `wp-json`、Sitecore Content Hub `api/`、以及普遍存在的 `sitemap.xml`），少量国内站有站内 ajax/getJSON 接口。

## 分类结果（150 个，已排除 7 个电商站）

| 类别 | 数量 | 结论 |
| --- | --- | --- |
| 政策机构（gov.cn 及各部委/国资委） | 75 | 基本全部服务端渲染；`pushinfo` 是中央共享 feed；维持 XPath。少数有搜索/下载接口（非新闻列表）。 |
| 国外技术服务 | 19 | 多为 Sitecore/WordPress/自定义 CMS，普遍有 `sitemap.xml`；部分有 `wp-json`/Sitecore Content Hub `api/`。**优先改用 sitemap/REST**。 |
| 国际管道 | 17 | 同上，多数有 `sitemap.xml`；个别用 Sitecore（oneok）或自定义 API。 |
| 新能源 | 6 | 服务端渲染为主；nengyuanjie.net 有 `$.getJSON`。 |
| 智能化 | 7 | 服务端渲染为主；zhihuiya.com 有付费开放平台 REST；udesk.cn 有 sitemap。 |
| 机器人 | 7 | 服务端渲染；standard-robots.com 403 反爬。 |
| 标准化管理 | 2 | std.samr.gov.cn 有 `/search/std?q=` 搜索接口（非新闻）。 |
| 泵机组 | 1 | 服务端渲染。 |
| 电气 | 5 | 论坛/技术社区，服务端渲染；autofg.com 等无接口。 |
| 知识产权与对外交流 | 4 | pss-system 412 反爬；zhihuiya 付费 API；cnipa/prci 服务端渲染。 |
| 管道技术 | 1 | youqichuyun.com（gbk 编码）+ sitemap。 |
| 管道检测 | 6 | prci/onstream 202 反爬；rosen-group/roseninspection 有 Sitecore Content Hub `api/`。 |
| 压缩机组相关 | 2 | 服务端渲染。 |

## 反爬 / 异常（需单独处理）

- `nhc.gov.cn`（412）、`pss-system.cponline.cnipa.gov.cn`（412）、`standard-robots.com`（403）、`app.mps.gov.cn`（502）、`xxgk.mca.gov.cn`（连接被重置）、`prci.org`/`onstream-pipeline.com`（202 反爬页）。
- `bakerhughes.com` / `technipfmc.com`：Incapsula（Imperva）反爬。`requests`（浏览器 UA）能取到真实 sitemap，但 Scrapy 下载器只拿到 bot 挑战页（bakerhughes 返回 213 字节的 `<script src="/_Incapsula_Resource...">`，technipfmc 返回 HTML 而非 XML）。这类挑战需要执行 JS 设 cookie，Scrapy 无法直接过；sitemap spider 已按正确接口实现，但在本机环境会 0 产出，需换网络/代理或另行处理。

## 两个工程坑（改写成接口型 spider 前必读）

1. **Scrapy 2.16 的入口是 `async def start()`，`start_requests()` 是死代码。** 本项目 pin 的 Scrapy 不再调用 `start_requests`；引擎调用 `start()`（默认遍历 `start_urls`）。自定义起始 URL / meta / 多栏目入口必须写成 `async def start()`。
2. **本机 fake-IP 代理会被 SSRF 中间件误伤。** 开发机把外部域名解析到 `198.18.0.0/15`（保留段）+ `fd00::/8`（ULA），`app/middlewares.py` 的 SSRF 下载器中间件因此拦截**所有**公网站点。不要关 SSRF；在每个 spider 的 `custom_settings` 里加 `"SSRF_ALLOWED_HOSTS": ["<host>", "*.<host>"]` 放行本站自身域名。curl / `requests` 能通是因为它们不做 SSRF 检查。

## 采集范围约定

用户明确要求「全部的栏目的数据都需要」——每个站点要采全所有栏目（栏目/板块），不能只采「新闻」。对 WordPress 站点要枚举所有内容型 post type（`/wp-json/wp/v2/types` 里 `show_in_rest` 且非参考数据），并把栏目写进 `source_category`（如 `国际管道·能源洞察`）。

## 已完成改写

直连 WordPress REST API（`async def start` + 全栏目 + `X-WP-TotalPages` 分页 + 站点自身 SSRF 放行），由 `tools/generate_wp_spiders.py` 生成：

- `036_williams_com.py` — 500 新闻 + 50 可持续发展报告 + 22 能源洞察 + 14 项目进展 + 12 视频。
- `004_cooperservices_com.py` — 新闻 64 + 活动 + 案例。
- `014_previan_com.py` — 新闻 51。
- `027_gasgrid_fi.py` — 新闻 154 + 项目 + 播客 + 材料 + 活动 + 公告。
- `028_gassco_eu.py` — 新闻 156 + 项目。
- `013_mears_net.py` — 新闻 1（存量极少）。

直连 sitemap.xml（`async def start` + 全栏目 + URL 路径归类栏目 + 详情页 XPath 提取），由 `tools/generate_sitemap_spiders.py` 生成：

- `023_enbridge_com.py` — stories / viewpoints / media-center / line-5-newsroom（Sitecore）。
- `033_oneok_com.py` — Newsroom 全栏目（company-news / press-releases / stories / earnings / leadership-perspectives / our-people / community / projects-and-operations）。
- `035_tcenergy_com.py` — announcements / newsroom / news-and-events（日期取 URL 内嵌 + `*[@class~='date']`）。
- `032_nationalgas_com.py` — media/news / publications / ngm-latest-news / operational-news。
- `026_natrangroupe_com.py` — medias 全栏目（Drupal，fr+en）。
- `020_worley_com.py` — insights（our-news / our-thinking）/ case-studies。
- `016_statsgroup_com.py` — news / case-studies / video / events。
- `145_rosen_group_com.py` — en media-and-events / expertise blog。
- `003_cbmm_com.py` — midias / media-center（pt）。
- `015_rmg_com.py` — publications / publikationen 等多语出版物。
- `029_gasunie_nl.py` — news / newsletter / expertise（英文 sitemap `?lang=en_GB`；日期取 `meta-item-date`）。
- `150_ndt_global_com.py` — news / blog / case-study / white-paper / event（排除 4 个方案分类落地页）。
- `146_tdwilliamson_com.py` — news / case-studies / papers / webinars（标题兜底 og:title，避开「Case Study / Media Release」栏目标签）。
- `021_apa_com_au.py` — news 下 asx-and-media-releases / transmission-industry-insights / case-studies（Next.js，1038 详情页）。
- `031_kindermorgan_com.py` — 主站 Energy-Delivered 故事 / KM-Treating 新闻 / Energy-Realities（sitemap）。注：真正的高价值 IR 新闻稿在 `ir.kindermorgan.com`（Q4 平台 JS 渲染），`rss/pressrelease.aspx` 只给最近 10 条且无正文，`/api/*` 全 404，待单独处理。
- `024_fluxys_com.py` — news 下 10 个业务栏目 + press-releases（6 语言 sitemap，采英文；日期从 URL slug 的 `YYMMDD`/`YYYYMMDD` 提取）。
- `125_bakerhughes_com.py`、`018_technipfmc_com.py` — 已按 sitemap 接口实现，但被 Incapsula 反爬挡住（见上文）。

其余国外站（energytransfer/evraz/cybernetix/us.endress/krohne/apa/kindermorgan 等）`wp-json` 返回 HTML 或 sitemap 无详情页 / 需子域 sitemap，待逐站继续；dnv.com/colpipe.com 返回 403，需单独处理。

## 下一步（按优先级）

1. **继续国外企业站 sitemap/REST 直连**：还剩 `kindermorgan.com` 的 IR 新闻稿（Q4 平台 JS 渲染，主站 sitemap 已采集，见上）、`energytransfer.com`（sitemap 空）、`evraz.com`（连接超时/被墙）、`gailonline.com`（sitemap 404）、`gazprom.com`（连接超时/被墙）、`snam.it`（已有 `snam_sitemap_rescue`）、`siemens-energy.com`（global/en sitemap 980 条几乎全是产品页、无新闻 feed，需另挖 AEM/媒体子域）、`pipesurveyinternational.com`（wp-json 存在但 posts 为空、站内仅 ~19 页）、`enduropls.com`（92 页仅 `/blog`）等；反爬的 dnv/colpipe/krohne/bakerhughes/technipfmc 单独处理。
2. **nengyuanjie.net / std.samr.gov.cn 等确有站内接口的国内站**，逐个抓包确认接口 URL、方法与分页参数后改写。
3. 政府站与纯服务端渲染站点：维持 XPath，仅对 selectors 做逐站校验。
