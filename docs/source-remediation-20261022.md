# 来源抓取修复与排除说明（2026-10-22）

本文记录上一轮全量审计中 52 个“有访问页面但零产出”来源的处理结果。运行产物仍以 `run_reports/` 为准，本文只保留稳定的工程结论和排除原因。

## 已落实的控制

- 行业 spider 通过 `tools/run_industry_batches.py` 按来源分批运行。
- `--max-pages` 是每站硬预算。请求发出前先预留页额，响应解析时释放，避免并发响应同时看到空位而越界。
- 批次报告的 `source_results` 会标记 `pass`、`zero_yield`、`fail`，并单列 `zero_yield_sources` 和 `budget_violations`。
- 网络失败来源先运行 `tools/discover_source_endpoints.py` 探测 robots、RSS、sitemap、HTML 和公开 API。
- 行业和公司来源使用来源级 profile 固定真实栏目、详情 URL 模式、正文选择器和日期选择器。

## 重点特殊来源

| 来源 | 处理方式 |
| --- | --- |
| 国家石油天然气管网集团有限公司 - 管网百科 | 解码页面 `article_meta_data`，再调用 `data/article/articleFulltextData` 获取全文 |
| 美国石油学会（API） | 官方 sitemap 发现新闻详情页，正文限定在 `.one-column` |
| Onstream Pipeline Inspection | 使用 MISTRAS 公开新闻 API，已验证第二页新增 50 条，越界返回 500 |
| PPSA | 抓取 newsletter 归档和 PDF 附件元数据，已验证两期归档和越界空壳 |
| Snam SpA | 通过独立 `snam_sitemap_rescue` 使用 sitemap 与 AEM page model |
| 国家金融监督管理总局 | 通过独立 `nfra_news` 使用栏目 JSON 和 `docId` 详情 API，避免解析静态壳页 |
| RMG Messtechnik GmbH | 使用官方 Press 栏目和 `i-<id>-<slug>` 详情规则，已产出真实条目 |

## 移出活动清单

| 来源 | 分类 | 原因 |
| --- | --- | --- |
| DNV | 反爬阻断 | 首页、新闻页、robots、sitemap 在直连和代理下持续 403 |
| Colonial Pipeline | 反爬阻断 | 首页、newsroom、robots、sitemap 持续 403 |
| Energy Transfer | 反爬阻断 | 首页、新闻页、robots、sitemap 持续 403 或 TLS 失败 |
| National Grid Gas plc | 反爬阻断 | 首页、新闻页、robots、sitemap 持续 403 |
| Mears Group, Inc. | 反爬阻断 | sitemap 可读，但全部详情页返回 Cloudflare 403 challenge |
| Endress+Hauser | 反爬阻断 | 首页、newsroom、robots、sitemap-index 均返回同一 JavaScript Challenge |
| GAIL (India) - Gas Transmission | 无公开可爬新闻源 | 官方站为 Angular 空壳；sitemap 仅 6 个企业页面，无新闻/RSS/JSON feed |
| 江苏省国有资产监督管理委员会 | 反爬阻断 | 首页和 2026 新闻栏目均被 Knownsec CloudWAF 以 403 拦截 |
| 海南省国有资产监督管理委员会 | robots 禁止 | 当前新闻条目只指向 `mp.weixin.qq.com`，其 robots.txt 禁止抓取 |
| 斯坦德机器人 | 反爬阻断 | 首页、robots、sitemap 持续 403 |
| 公安部 | 反爬阻断 | 首页、栏目、robots、sitemap 在直连和代理下持续 521 |
| 国际管道大会（IPC） | 无效 URL | 配置域名不可解析 |

## 仍需全量确认

- 油气储运网已接入官方 sitemap 和论坛详情规则，但 20 页小样本仍落在低正文帖子，未达到正文阈值；需要全量批次确认帖子质量和筛选阈值。
- 中国能源网详情页由页面挑战脚本延迟生成正文，sitemap、RSS 和常规 API 均未发现可替代源；当前限页实测仍未产出，暂不从公开新闻源中永久移除。
- 集邦新能源网当前 TLS 连接持续中断，尚未得到可复现的 RSS、sitemap 或 API；暂不从“公开新闻源”中永久移除。

全量运行完成后，以 `tools/summarize_run_report.py` 生成的 `audit_report.json` 为准，不应仅凭小样本判断站点长期可用性。
