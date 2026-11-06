# MCP 使用与注册

本文档说明本模板项目里 MCP 放在哪里、怎么注册、怎么启用，以及哪些内容应该提交。

## 放置位置

| 路径 | 作用 | 是否提交 |
| --- | --- | --- |
| `.codex/config.toml` | 项目本地 Codex 配置，也是 MCP 注册表 | 可以提交 |
| `.codex/mcp/` | MCP 服务源码、本地依赖和构建产物 | 不提交 |
| `.codex/skills/` | 项目可复用的爬虫、逆向、调试技能 | 按项目需要提交，运行产物不提交 |

项目里的 MCP 不需要散落到业务代码中。注册只维护 `.codex/config.toml`，源码统一放 `.codex/mcp/`。

## 注册规则

项目级 MCP 使用 `.codex/config.toml` 里的 `[mcp_servers.<name>]` 区块注册。

注意：因为配置文件在 `.codex/config.toml`，所以 `cwd` 的相对路径按 `.codex/` 目录解析。也就是说，本项目里应该写：

```toml
cwd = "./mcp/reqable-mcp"
```

不要按项目根目录再多写一层 `.codex/`。

通用格式：

```toml
[mcp_servers.my-server]
command = "启动命令"
args = ["参数1", "参数2"]
cwd = "./mcp/my-server"
```

`name` 建议稳定、短小、语义清楚，例如 `reqable-mcp`、`adspower-browser`、`frida-mcp`。后续在 `/mcp` 或工具列表里也会按这个名字识别。

## 当前启用的 MCP

```toml
[mcp_servers.chrome-devtools-mcp]
command = "cmd"
args = ["/c", "npx", "-y", "chrome-devtools-mcp@latest", "--browser-url=http://127.0.0.1:9222"]

[mcp_servers.reqable-mcp]
command = "uv"
args = ["run", "reqable-mcp"]
cwd = "./mcp/reqable-mcp"

[mcp_servers.adspower-browser]
command = "cmd"
args = ["/c", "pnpm", "build", "&&", "node", "build/index.js"]
cwd = "./mcp/adspower-browser/packages/local-api-mcp"
```

含义：

- `chrome-devtools-mcp`：通过 `npx` 启动 MCP，并连接本机 `9222` 端口上的调试 Chrome。
- `reqable-mcp`：在 `.codex/mcp/reqable-mcp` 目录用 `uv run` 启动。
- `adspower-browser`：在 AdsPower MCP 子目录先执行 `pnpm build`，再启动 `node build/index.js`。

## 当前保留但默认禁用的 MCP

这些 MCP 源码保留在 `.codex/mcp/`，对应区块在 `.codex/config.toml` 中默认注释。需要使用时取消注释并刷新 MCP 配置。

| Server 名 | 目录 | 启动方式 |
| --- | --- | --- |
| `frida-mcp` | `.codex/mcp/frida-mcp` | `uv run frida-mcp` |
| `ida-pro-mcp` | `.codex/mcp/ida-pro-mcp` | `uv run ida-pro-mcp` |
| `jadx-mcp` | `.codex/mcp/jadx-mcp` | `uv run jadx_mcp_server` |
| `js-reverse-mcp` | `.codex/mcp/js-reverse-mcp` | `npm run start` |
| `wedecode-mcp` | `.codex/mcp/wedecode-mcp` | `npm run mcp` |
| `wire-mcp` | `.codex/mcp/wire-mcp` | `node index.js` |

## 配套 Skills

项目本地 skills 放在 `.codex/skills/`，目录名必须和 `SKILL.md` 的 `name` 一致。当前配套名称：

```text
captcha-solve
env-patch
js-deobfuscate
param-sign
scrapy-spider
web-reverse
web-reverse-debug
web-reverse-plan
web-reverse-reproduce
web-reverse-route
web-reverse-run
web-reverse-triage
```

## 启用和禁用

启用一个 MCP：

1. 确认源码目录在 `.codex/mcp/<server>`。
2. 确认该 MCP 的依赖已安装，启动命令可以在本地跑通。
3. 在 `.codex/config.toml` 添加或取消注释对应 `[mcp_servers.<name>]` 区块。
4. 重启 Codex、重启 IDE 扩展，或在支持的客户端里刷新 MCP 配置。
5. 在 Codex 里输入 `/mcp` 查看是否已连接。

禁用一个 MCP：

```toml
# [mcp_servers.frida-mcp]
# command = "uv"
# args = ["run", "frida-mcp"]
# cwd = "./mcp/frida-mcp"
```

直接注释整个区块即可。不要删除 `.codex/mcp/` 里的源码，除非确认以后不再使用。

## 新增 MCP

新增 MCP 推荐按这个流程：

1. 把 MCP 仓库放到 `.codex/mcp/<server-name>`。
2. 阅读该 MCP 自己的 README，确认启动方式是 `uv run`、`npm run`、`pnpm`、`node` 还是其他命令。
3. 在 `.codex/config.toml` 注册：

```toml
[mcp_servers.example-mcp]
command = "uv"
args = ["run", "example-mcp"]
cwd = "./mcp/example-mcp"
```

如果是 Node 服务：

```toml
[mcp_servers.example-node-mcp]
command = "node"
args = ["build/index.js"]
cwd = "./mcp/example-node-mcp"
```

如果是远程 HTTP MCP，则不用 `cwd`，改用 `url`：

```toml
[mcp_servers.example-http-mcp]
url = "https://example.com/mcp"
```

## 验证方式

基础验证：

```bash
codex mcp list
```

进入 Codex 会话后：

```text
/mcp
```

如果 MCP 已正常加载，应该能看到对应 server 和它暴露的 tools。

Chrome 调试 MCP 需要先启动调试浏览器：

```bat
.codex\mcp\start_chrome.bat
```

启动后验证调试端口：

```bash
curl http://127.0.0.1:9222/json/version
```

也可以单独验证本地启动命令：

```bash
cd .codex/mcp/reqable-mcp
uv run reqable-mcp
```

```bash
cd .codex/mcp/adspower-browser/packages/local-api-mcp
pnpm build
node build/index.js
```

## 环境变量和密钥

不要把 token、cookie、账号密码直接写进可提交的 `.codex/config.toml`。

推荐做法：

```toml
[mcp_servers.some-private-mcp]
command = "node"
args = ["index.js"]
cwd = "./mcp/some-private-mcp"
env_vars = ["SOME_PRIVATE_TOKEN"]
```

然后在本机环境变量、用户级 `~/.codex/config.toml` 或未提交的本地启动脚本里维护真实密钥。

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| `/mcp` 看不到 server | 项目是否已信任，Codex 是否重启或刷新配置 |
| 提示找不到目录 | `cwd` 是否按 `.codex/` 目录写成 `./mcp/...` |
| 提示找不到命令 | `node`、`npm`、`pnpm`、`uv` 是否在 PATH 中 |
| Node MCP 启动失败 | 是否执行过 `npm install` 或 `pnpm install` |
| Python MCP 启动失败 | MCP 仓库是否有 `pyproject.toml`，`uv run ...` 是否能单独跑通 |
| 工具出现但不可用 | MCP 依赖的浏览器、Reqable、AdsPower、设备或代理服务是否已启动 |

## 提交边界

推荐提交：

- `.codex/config.toml`
- `docs/mcp-usage.md`
- 必要的 `.codex/skills/**/SKILL.md` 和轻量脚本

不要提交：

- `.codex/mcp/`
- `.codex/skills/**/node_modules/`
- `build/`、`dist/`、缓存、浏览器数据、调试输出
- 任何密钥、cookie、账号密码

这样模板仓库只保留注册方式和使用说明，具体 MCP 源码和依赖由每台机器本地准备。
