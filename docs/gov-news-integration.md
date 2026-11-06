# 政府官网新闻爬虫集成说明

旧项目 `官网新闻/spiders` 已整合到本项目：

```text
app/spiders/gov_news/
```

运行产物统一放在：

```text
run_reports/gov_news/
```

当前从旧项目迁移了一份初始数据：

```text
run_reports/gov_news/news_data.js
```

## 常用命令

列出 Scrapy 能识别的爬虫：

```powershell
Set-Location D:\实习\news-pipelines
python -X utf8 -m scrapy list
```

查看当前政府新闻数据统计：

```powershell
python -X utf8 app\spiders\gov_news\run_my_crawler.py --mode check
```

严格只从用户给定官网链接爬：

```powershell
python -X utf8 -m scrapy crawl official_only -a max_pages=0 -a max_items=0 -a output=run_reports\gov_news\_crawl_tmp\official_only_news.js
```

检查严格官网输出是否混入外部域名：

```powershell
python -X utf8 app\spiders\gov_news\check_official_only_output.py --input run_reports\gov_news\_crawl_tmp\official_only_news.js
```

严格官网全量爬取并自动审计：

```powershell
python -X utf8 app\spiders\gov_news\run_strict_official_full_crawler.py --mode both --max-pages 0 --max-items 0 --browser-max-pages 0 --browser-max-items 0 --headless 0 --manual-wait 60
```

使用项目统一 runner 调度已注册 spider：

```powershell
python -X utf8 run_spider.py --spider official_only --fresh
```

## 已注册的政府新闻 spider

```text
gov_news
rescue_news
gov_repost
sasac_local_repost
nhc_news
official_gap_news
official_only
official_only_browser
```

