# 官网新闻 Scrapy 项目说明

本项目已经整理为 Python Scrapy 框架模式。

## 目录结构

```text
官网新闻/
├─ scrapy.cfg
├─ index.html
├─ news_data.js
├─ spiders/
│  ├─ settings.py
│  ├─ items.py
│  ├─ pipelines.py
│  ├─ middlewares.py
│  ├─ gov_news_spider.py
│  ├─ rescue_news_spider.py
│  ├─ gov_repost_spider.py
│  ├─ sasac_local_repost_spider.py
│  ├─ site_spider.py
│  └─ run_my_crawler.py
├─ site_news/
├─ backups/
└─ _crawl_tmp/
```

## 常用运行方式

进入项目目录：

```powershell
Set-Location D:\实习\官网新闻
```

查看 Scrapy 能识别到的爬虫：

```powershell
python -X utf8 -m scrapy list
```

运行主爬虫：

```powershell
python -X utf8 -m scrapy crawl gov_news -a max_pages=30 -a max_items=50 -a output=_crawl_tmp\base_news_data.js
```

运行补爬爬虫：

```powershell
python -X utf8 -m scrapy crawl rescue_news -a source=教育部,司法部,国家档案局 -a max_pages=80 -a max_items=80 -a output=_crawl_tmp\rescue_news_data.js
```

运行中国政府网转载补爬：

```powershell
python -X utf8 -m scrapy crawl gov_repost -a max_pages=0 -a max_items=0 -a output=_crawl_tmp\gov_repost_news.js
```

运行国务院国资委地方国资转载补爬：

```powershell
python -X utf8 -m scrapy crawl sasac_local_repost -a source=all -a max_pages=80 -a max_items=80 -a output=_crawl_tmp\sasac_local_repost.js
```

运行国家卫生健康委员会专用爬虫：

```powershell
python -X utf8 -m scrapy crawl nhc_news -a max_pages=80 -a max_items=80 -a output=_crawl_tmp\nhc_news.js
```

如果卫健委页面仍然返回 `412` 或空白页，用可见浏览器手动等待模式：

```powershell
python -X utf8 -m scrapy crawl nhc_news -a headless=0 -a manual_wait=20 -a max_pages=80 -a max_items=80 -a output=_crawl_tmp\nhc_news.js
```

补爬“当前没有官网直采数据”的来源：

```powershell
python -X utf8 -m scrapy crawl official_gap_news -a headless=0 -a manual_wait=20 -a max_pages=120 -a max_items=80 -a output=_crawl_tmp\official_gap_news.js
```

这个命令会自动从 `news_data.js` 里找出没有官网直采新闻的来源，再用真实 Edge 浏览器补爬。遇到宁夏这类安全验证页时，可以把 `manual_wait` 调大，例如 `60`。

一条命令完成“补爬 + 备份 + 合并到网页数据”：

```powershell
Set-Location D:\实习
python -X utf8 官网新闻\spiders\run_official_gap_crawler.py --manual-wait 60 --max-pages 120 --max-items 80
```

只从用户最初给定官网链接中爬取新闻：

```powershell
Set-Location D:\实习\官网新闻
python -X utf8 -m scrapy crawl official_only -a max_pages=300 -a max_items=300 -a output=_crawl_tmp\official_only_news.js
```

检查输出是否全部来自给定官网域名：

```powershell
Set-Location D:\实习
python -X utf8 官网新闻\spiders\check_official_only_output.py --input 官网新闻\_crawl_tmp\official_only_news.js
```

严格官网全量爬取，并自动审计哪些网站还没跑出来：

```powershell
Set-Location D:\实习
python -X utf8 官网新闻\spiders\run_strict_official_full_crawler.py --mode both --max-pages 0 --max-items 0 --browser-max-pages 0 --browser-max-items 0 --headless 0 --manual-wait 60
```

运行结束后看这个报告：

```text
官网新闻\_crawl_tmp\official_only_audit_report.txt
```

## 推荐的一键运行方式

从外层目录运行：

```powershell
Set-Location D:\实习
python -X utf8 官网新闻\spiders\run_my_crawler.py --mode check
python -X utf8 官网新闻\spiders\run_my_crawler.py --mode rescue
```

`run_my_crawler.py` 会先备份主数据，再爬取到临时文件，最后安全合并，避免直接覆盖 `news_data.js` 导致新闻变少。

## 当前主数据

前端读取的主数据文件：

```text
官网新闻/news_data.js
```

打开网页：

```powershell
.\官网新闻\index.html
```
