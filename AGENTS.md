# AGENTS.md 项目协作说明

本文档面向 Codex、Claude Code、Cursor Agent 等 AI 编程助手，也适合新成员快速理解本项目的工程边界。它不是 Scrapy 运行依赖文件，但会影响 Agent 接手项目时的判断。

## 项目快照

`app` 是一个使用 `uv` 管理的 Scrapy 爬虫模板项目。

- 项目类型：Python Scrapy 爬虫模板 / CLI 工具
- Python 版本：`>=3.12`
- 统一运行入口：`run_spider.py`
- Scrapy 配置入口：`app/settings.py`
- 环境变量模板：`.env.example`
- 本地环境配置：`.env`，禁止提交
- 运行状态目录：`run_state/`，禁止提交
- 运行报告目录：`run_reports/`，禁止提交
- 数据库契约：`docs/database-contract.md`
- MySQL 迁移示例：`migrations/mysql/001_create_rss_news.sql`

## 工作原则

- 优先保持项目现有架构，不要把通用运行逻辑塞进单个 spider。
- `run_spider.py` 应保持为薄入口，只负责 CLI、`SPIDER_RUN_NAMES`、`SPIDER_CONFIGS` 和调度调用。
- spider 文件只写站点抓取、解析和站点级请求逻辑。
- 可复用运行逻辑放入 `app/runtime/`。
- 通用字段清洗、去重、hash、入库逻辑放入 `app/pipelines.py` 和 `app/item_deduplication.py`。
- Scrapy 全局行为放入 `app/settings.py`，本地差异通过 `.env` 配置。
- 辅助脚本放入 `tools/`；如果脚本中出现可复用业务逻辑，应下沉到 `app/` 包内。
- 数据库表由外部迁移或数据库侧维护，爬虫 pipeline 只写入已存在的表。

## CodeGraph 使用规则

本仓库根目录存在 `.codegraph/`。理解或定位代码时，应先使用 CodeGraph，再考虑 `rg` 或直接读取文件。

- MCP 工具可用时：优先使用 `codegraph_explore`
- Shell fallback：

```bash
codegraph explore "<symbol names or question>"
```

适合用 CodeGraph 的场景：

- 理解 `run_spider.py` 到 Scrapy 子进程的运行链路
- 查找某个函数、类、模块的调用关系
- 修改 runtime、pipeline、middleware、monitor 等 Python 代码前确认影响面

可以直接读取的内容：

- README、AGENTS、docs 等文档
- `.env.example`、`pyproject.toml`、Dockerfile、CI 配置
- 修改后的精确验证内容

## 权威配置位置

| 配置内容 | 权威位置 |
| --- | --- |
| 默认运行哪些 spider | `run_spider.py` 的 `SPIDER_RUN_NAMES`（由 `discover_spider_configs()` 自动生成，除 `example` 外全部扁平站点 spider） |
| 每个 spider 的元数据和运行差异 | spider 类属性（`entry_url`/`section_urls`/`start_urls`/`site_name`/`site_type`/`language`），由 `app/runtime/spider_configs.py` 的 `discover_spider_configs()` 读取 |
| Scrapy 全局设置 | `app/settings.py` |
| 本地环境、数据库、日志、监控开关 | `.env` |
| 环境变量示例 | `.env.example` |
| MySQL 表结构与字段契约 | `docs/database-contract.md` 和 `migrations/mysql/001_create_rss_news.sql` |
| Agent 工作规则 | `AGENTS.md` |
| 用户项目说明 | `README.md` |

同一个事实应只保留一个权威位置。文档可以引用权威位置，但不要复制出互相矛盾的配置。

## 常用命令

安装依赖：

```bash
uv sync
```

列出 spider：

```bash
uv run scrapy list
```

运行配置校验：

```bash
uv run python tools/validate_spider_configs.py --check-available
```

dry-run：

```bash
uv run python run_spider.py --dry-run
```

运行默认清单：

```bash
uv run python run_spider.py
```

运行指定 spider：

```bash
uv run python run_spider.py --spider example
```

单元测试：

```bash
uv run python -m unittest discover -s tests -v
```

编译检查：

```bash
uv run python -m compileall run_spider.py app tools tests
```

Lint：

```bash
uv run --with ruff ruff check run_spider.py app tools tests
```

依赖审计：

```bash
uv run --with pip-audit pip-audit
```

Docker 验证：

```bash
docker build -t scrapy-template:local .
docker run --rm scrapy-template:local python run_spider.py --dry-run
```

## 新增或重命名 spider 流程

1. 在 `app/spiders/` 下新增或修改扁平站点 spider（`NNN_<host>.py`，自包含）。
2. 确认 spider 类继承 `scrapy.Spider`，设置唯一 `name`，并填写站点元数据（`site_id`、`site_name`、`site_type`、`language`、`entry_url`、`section_urls`、`start_urls`）。
3. 无需手工维护配置：`run_spider.py` 通过 `discover_spider_configs()` 自动发现，`SPIDER_CONFIGS` 与 `SPIDER_RUN_NAMES` 随 `scrapy list` 动态生成。
4. 校验：

```bash
uv run scrapy list
uv run python tools/validate_spider_configs.py --check-available
uv run python run_spider.py --dry-run
```

## 修改数据库字段流程

如果新增、删除或重命名入库字段，必须同步修改：

- `app/items.py`
- `app/pipelines.py` 中的 `MySQLItemPipeline.COLUMNS`
- `migrations/mysql/001_create_rss_news.sql`
- `docs/database-contract.md`
- `tests/test_mysql_pipeline.py`

注意：

- `MYSQL_ENABLED=0` 时不连接 MySQL。
- 项目不会自动建表。
- `url_hash` 是默认主键和 upsert 依据。
- `publish_time` 入库格式为 MySQL `DATETIME(3)`。

## 安全规则

- 不要提交 `.env`、数据库密码、Token、代理凭据、监控 endpoint 密钥。
- 不要关闭 SSRF 防护，除非任务明确要求并有 allowlist。
- 访问内网、本机或特殊地址时，优先通过 `SSRF_ALLOWED_HOSTS` 明确放行。
- 非本地环境的 `SPIDER_MONITOR_ENDPOINT` 必须使用 HTTPS。
- 不要在日志和 dead letter 中默认输出完整敏感数据；完整行 dead letter 只能通过 `MYSQL_DEAD_LETTER_INCLUDE_ROWS=1` 显式开启。
- 不要使用字符串拼接构造来自外部输入的 SQL。

## 测试与验证规则

修改 Python 逻辑后，至少运行：

```bash
uv run python -m unittest discover -s tests -v
uv run python -m compileall run_spider.py app tools tests
uv run python tools/validate_spider_configs.py --check-available
uv run python run_spider.py --dry-run
```

修改依赖、CI、Docker 或部署相关内容时，根据影响面补充：

```bash
uv sync --locked
uv run --with ruff ruff check run_spider.py app tools tests
uv run --with pip-audit pip-audit
docker build -t scrapy-template:local .
docker run --rm scrapy-template:local python run_spider.py --dry-run
```

只修改文档时，至少检查：

```bash
git diff --check -- README.md AGENTS.md docs
```

## 目录与提交规则

允许提交：

- `run_spider.py`
- `app/`
- `tools/`
- `tests/`
- `docs/`
- `migrations/`
- `README.md`
- `AGENTS.md`
- `.env.example`
- `pyproject.toml`
- `uv.lock`
- `Dockerfile`
- `.github/workflows/`
- `.codex/config.toml`，仅当团队确实共享项目 MCP 注册表
- `.codex/skills/`，仅当团队确实共享这些项目专用 skills

禁止提交：

- `.env`
- `.venv/`
- `.codegraph/`
- `.codex/mcp/`
- `run_state/`
- `run_reports/`
- `.scrapy/`
- `httpcache/`
- `*.log`
- 抓取产出文件，例如 `output.json`、`output.jsonl`、`output.csv`

## Codex 本地工具规则

- `.codex/config.toml` 是项目 MCP 注册表，`cwd` 值相对于 `.codex/`。
- `.codex/mcp/<server>` 是本地 MCP 仓库目录，不提交。
- `.codex/skills/<skill>` 是项目专用 skill 目录。
- `.codex/skills/<skill>` 目录名必须与对应 `SKILL.md` 的 `name` 字段一致。
- 通用 skill 更适合放在用户级目录：`C:\Users\admin\.codex\skills\`。
- 项目专用 skill 才放在仓库内：`.codex/skills/`。

Windows 下验证项目内 skill：

```powershell
$env:PYTHONUTF8='1'
python C:\Users\admin\.codex\skills\.system\skill-creator\scripts\quick_validate.py .codex\skills\<skill>
```

## Git 工作区注意事项

- 当前工作区可能存在用户或其他 Agent 的未提交修改。
- 不要使用 `git reset --hard`、`git checkout --` 等破坏性命令，除非用户明确要求。
- 不要回滚自己没有创建的修改。
- 如果必须编辑已有改动的文件，先理解当前 diff，再做最小必要修改。
- 不要把运行产物、缓存目录或本地密钥加入提交。

## 文档维护规则

- `README.md` 面向人类使用者，重点解释项目怎么理解、怎么运行、怎么扩展。
- `AGENTS.md` 面向 AI/Agent，重点记录边界、命令、禁止事项和修改流程。
- `docs/project-overview.md` 面向架构补充，不要和 README 写出冲突内容。
- `docs/database-contract.md` 是数据库契约，字段变更必须同步更新。

## 快速判断

如果不确定某段逻辑放哪里，按下面判断：

| 问题 | 放置位置 |
| --- | --- |
| 这个 spider 是否默认运行 | `run_spider.py` / `SPIDER_RUN_NAMES`（自动发现，除 `example` 外全部默认运行） |
| 这个 spider 的 URL、JOBDIR、超时、局部 setting | spider 类属性 + `discover_spider_configs()`（自动发现；局部 setting 写在 spider 的 `custom_settings`） |
| 这是 Scrapy 全局行为 | `app/settings.py` |
| 这是站点解析逻辑 | `app/spiders/<name>.py` |
| 这是通用运行调度逻辑 | `app/runtime/` |
| 这是字段清洗、hash、入库 | `app/pipelines.py` 或 `item_deduplication.py` |
| 这是配置生成、校验、watch | `tools/` |
| 这是用户运行说明 | `README.md` |
| 这是 Agent 协作规则 | `AGENTS.md` |
