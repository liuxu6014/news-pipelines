# Database Contract

本项目不会自动建表。开启 `MYSQL_ENABLED=1` 前，数据库侧必须先准备好目标表，并保证字段、唯一键和索引与这里一致。

## Required Table

默认表名来自 `.env` 的 `MYSQL_TABLE`，默认值是 `rss_news`。

```sql
CREATE TABLE rss_news (
  title VARCHAR(512) NULL,
  url TEXT NOT NULL,
  canonical_url VARCHAR(1024) NOT NULL,
  url_hash CHAR(64) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  content LONGTEXT NULL,
  content_md LONGTEXT NULL,
  summary TEXT NULL,
  publish_time DATETIME(3) NULL,
  author VARCHAR(255) NULL,
  source VARCHAR(255) NULL,
  source_site VARCHAR(255) NULL,
  source_category VARCHAR(255) NULL,
  domain VARCHAR(255) NULL,
  image_url TEXT NULL,
  raw_item JSON NULL,
  first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (url_hash),
  KEY idx_domain (domain),
  KEY idx_source_site (source_site),
  KEY idx_publish_time (publish_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

## Write Semantics

- `url_hash` 是 `canonical_url` 的 SHA256，必须唯一。
- `ON DUPLICATE KEY UPDATE` 会在同一 URL 再次出现时更新内容字段，并刷新 `last_seen_at` / `updated_at`。
- `MYSQL_BATCH_SIZE` 控制批量 upsert 大小，默认 `100`；如果目标库压力较大，可以先调小到 `10` 或 `20`。
- `publish_time` 使用 `DATETIME(3)`；spider 应尽量输出 MySQL 可解析的 ISO-like 时间字符串，未知时间写 `NULL` 或空值。
- 失败死信默认只写 URL/hash 等定位键；只有显式开启 `MYSQL_DEAD_LETTER_INCLUDE_ROWS=1` 时才写完整行数据。
- `MYSQL_RETRY_TIMES` 只用于 transient MySQL 错误，例如连接丢失、deadlock、lock wait timeout；默认 `0`，生产可先设为 `2`。
- 字段增删必须同时更新 `app/pipelines.py` 的 `MySQLItemPipeline.COLUMNS` 和本文档。

## PostgreSQL Target（Kafka 消费链路）

Kafka → 数据库消费链路（`tools/kafka_consume.py`）写入外部的 `pipesight` PostgreSQL 库，目标是已有表 **`news_articles`**（不是 MySQL 的 `rss_news`）。该表由外部系统维护，本项目不建表、不迁移。

`news_articles` 关键字段与映射：

必填消息字段：`title`、`url`、`content_md`——缺任一个整条消息跳过（记 `missing_title_or_url`）。其余字段可选，多余字段忽略。

| 目标字段 | 类型 / 约束 | Kafka 消息来源 |
| --- | --- | --- |
| `source_id` | bigint NOT NULL，FK → `data_sources(id)` | 由 `site_name` / `domain` 匹配 `data_sources`，匹配不到则自动注册一行（`adapter='kafka'`） |
| `title` | varchar(1000) NOT NULL | `title` |
| `url` | text NOT NULL，唯一索引 `md5(url)` | `url` |
| `author` | text | `author` |
| `published_at` | timestamptz | `ctime`（Unix 秒 → UTC） |
| `content` | text | `content`（缺省回退必填的 `content_md`） |
| `content_zh` | text | 暂不写（NULL） |
| `category_id` | bigint，FK → `categories(id)` | 暂不写（NULL） |
| `is_pushed` | boolean NOT NULL，默认 false | 固定 false |

写语义：

- Upsert 使用 `INSERT ... ON CONFLICT (md5(url)) DO UPDATE`，重复 URL 时更新 `title/author/published_at/content/content_zh/category_id` 并刷新 `updated_at`；不覆盖 `source_id` / `url` / `is_pushed`。
- 配置来自 `.env` 的 `PG_*`：`PG_TABLE` 默认 `news_articles`，`PG_DATABASE` 默认 `pipesight`。
- 字段增删必须同时更新 `app/pipelines.py` 的 `NewsArticlesPipeline.COLUMNS` / `UPDATED_COLUMNS` 和本文档。

## 数据源表（爬虫起停）

150 个扁平站点 spider 的启停由 pipe-sight（主体项目 `D:\A_CODEBASE\pipe-sight`）的 **`data_sources`** 表控制，本项目不建表、不迁移该表，只读写已存在的行。

每行约定（`tools/seed_data_sources.py` 负责幂等写入）：

| 字段 | 值 |
| --- | --- |
| `name` | spider 的 `site_name`（人类可读，如「国家卫生健康委员会」） |
| `type` | `website`（`mp.weixin.qq.com` 时为 `wechat`） |
| `url` | spider 的 `entry_url` |
| `adapter` | 固定 `news_pipelines_spider` |
| `cron` / `next_run_at` | 均为 NULL（调度由本项目 `run_spider.py` 负责，不由 pipe-sight 调度器） |
| `config` | JSON：`spider_name`（匹配键，即 spider 的 `name`，如 `059_nhc_gov_cn`）、`site_id`、`site_type`、`language` |
| **`is_enabled`** | **启停开关：用户在 pipe-sight 数据源管理中切换；本项目据此决定是否运行该 spider** |

- 匹配键是 `config.spider_name`（唯一、稳定），不是 `name` 或 `url`。
- `run_spider.py` 仅在 `PIPESIGHT_SOURCE_GATE=1` 时读取本表，且只跑 `is_enabled=true` 的 spider；无对应行时按 `PIPESIGHT_SOURCE_GATE_ALLOW_UNKNOWN` 处理（默认允许，避免空表时全部停跑）。
- `run_spider.py` 连库失败时回退为运行全部 spider，控制面故障不阻断采集。
- 重新执行 `tools/seed_data_sources.py` 幂等，默认保留管理员已有的 `is_enabled` 选择；加 `--reactivate` 才恢复停用来源。
