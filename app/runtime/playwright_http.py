"""Playwright 真实浏览器渲染：把 JS/反爬站点渲染成静态 HTML。

curl_cffi 的 Chrome TLS 指纹能绕过「按 JA3 指纹拦截」的站（[[curl-cffi-tls-bypass]]），
但对「必须跑 JS 才能拿到正文」的站无能为力：瑞数/RiverSecurity 返回 412 + JS 壳，
Incapsula 返回 212 字节的 ``/_Incapsula_Resource`` 挑战，Cloudflare 返回「Just a
moment」，纯 JS SPA 返回空壳（``<div id="root">`` / ``<div id="app">``）。

这些站点对真实浏览器本来就放行，所以正确路径不是逆向其签名，而是用真实无头浏览器
（系统已装的 Chrome / Edge，``channel=`` 指定，无需 ``playwright install`` 下载内核）
执行挑战 JS、等它自动重载，再把渲染后的最终 DOM 交给 spider 用 XPath 提取。

为什么用**同步 API + 单线程执行器**：Scrapy 跑在 Twisted 的 asyncioreactor 上，Windows
下它是 ``SelectorEventLoop``，不支持 ``asyncio.create_subprocess_exec``（Playwright 的
node 驱动起不来）。Playwright 同步 API 在后台线程里自建 ``ProactorEventLoop``，绕开这个
限制。用 ``ThreadPoolExecutor(max_workers=1)`` 保证浏览器只被同一个线程访问（同步 API
非线程安全），再用 ``run_in_executor`` 把异步中间件桥接过去。
"""
import asyncio
import concurrent.futures
import logging
import re
import sys

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# 挑战残留标记：渲染结果里若还含这些，说明反爬挑战尚未放行，需要二次导航（第一次已种下 cookie）。
_CHALLENGE_RE = re.compile(
    r"incapsula|_incapsula_resource|incap_ses|visid_incap|request unsuccessful|incident id|"
    r"__cf_chl|just a moment|challenge-platform|cf-browser-verification|"
    r"riversecurity|jsl_clearance|_\$jsl",
    re.I,
)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class PlaywrightRenderer:
    """持有一个跨请求复用的无头浏览器，按需渲染 URL（同步 API + 单线程执行器）。"""

    def __init__(self, channel="chrome", headless=True, timeout=40.0):
        self._channel = channel
        self._headless = headless
        self._timeout = float(timeout)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._pw = None
        self._browser = None
        self._closed = False

    def _ensure_browser(self):
        if self._browser is None:
            # Windows 下 Twisted asyncioreactor 装了 WindowsSelectorEventLoopPolicy（不支持
            # asyncio 子进程），会让 Playwright 的 node 驱动 `create_subprocess_exec` 抛
            # NotImplementedError。这里在 worker 线程里切回 Proactor 政策——它只影响此后
            # 新建的事件循环，不影响已经在跑的 reactor 主循环。
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self._pw = sync_playwright().start()
            launch = {
                "headless": self._headless,
                # 去掉 navigator.webdriver 等自动化痕迹，降低被反爬识别的概率。
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            # 优先用系统 Chrome，其次 Edge（Windows 必装），都不行再回落 playwright 自带内核。
            for channel in (self._channel, "msedge"):
                try:
                    self._browser = self._pw.chromium.launch(channel=channel, **launch)
                    logger.info("Playwright 浏览器已启动（channel=%s）", channel)
                    break
                except Exception as exc:  # noqa: BLE001 - 逐个尝试可用内核
                    logger.warning("Playwright channel=%s 启动失败：%r", channel, exc)
                    self._browser = None
            if self._browser is None:
                self._browser = self._pw.chromium.launch(**launch)
                logger.info("Playwright 浏览器已启动（bundled chromium）")
        return self._browser

    def _render_sync(self, url):
        """在单线程执行器上运行：渲染 ``url``，返回 dict(url, html)。"""
        browser = self._ensure_browser()
        context = browser.new_context(
            user_agent=_DEFAULT_UA,
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
        )
        page = context.new_page()
        try:
            html = self._goto_and_settle(page, url)
            # 反爬挑战（Incapsula/Cloudflare/瑞数）第一次导航会返回挑战页并种下 cookie，
            # 同一上下文二次导航通常直接命中真实内容。
            if _CHALLENGE_RE.search(html):
                page.wait_for_timeout(1000)
                html = self._goto_and_settle(page, url)
            return {"url": page.url, "html": html}
        finally:
            context.close()

    def _goto_and_settle(self, page, url):
        page.goto(url, wait_until="domcontentloaded", timeout=self._timeout * 1000)
        # 反爬挑战（瑞数/Incapsula/Cloudflare）会执行 JS 后自动重载，等「load」再收尾。
        try:
            page.wait_for_load_state("load", timeout=self._timeout * 1000)
        except Exception:  # noqa: BLE001 - 超时也继续，能拿到多少算多少
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        # 逐段滚动到底：触发无限滚动 / 折叠在首屏之下的懒加载列表（如 pubscholar 的
        # 资讯卡片、部分 SPA 的列表在滚动后才渲染出 ``<a href>``）。滚到高度不再增长
        # 或到上限后回到顶部，再取 DOM。
        self._scroll_to_trigger_lazy(page)
        # 挑战 JS 与 SPA 渲染需要一点时间落定，再取 DOM。
        page.wait_for_timeout(2000)
        return page.content()

    @staticmethod
    def _scroll_to_trigger_lazy(page):
        try:
            last_height = 0
            for _ in range(12):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(350)
                height = page.evaluate("document.body.scrollHeight")
                if height == last_height:
                    break
                last_height = height
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:  # noqa: BLE001 - 滚动失败不影响已渲染的内容
            pass

    async def render(self, url):
        """异步入口：把渲染任务交给单线程执行器。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._render_sync, url)

    def _close_sync(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._close_sync)
        finally:
            self._executor.shutdown(wait=True)
