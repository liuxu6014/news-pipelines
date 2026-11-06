"""Spider 与 Downloader 中间件。"""

import asyncio
import fnmatch
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

from scrapy import signals
from scrapy.exceptions import IgnoreRequest, NotConfigured
from scrapy.http import HtmlResponse

from app.runtime.curl_http import curl_get
from app.runtime.playwright_http import PlaywrightRenderer

PROXY_RETRY_STATUSES = {403, 407, 429, 500, 502, 503, 504, 520, 521, 522, 525, 526}

# 非 HTML 资源不交给 Playwright 渲染（sitemap.xml / robots.txt / 图片 / 样式 / 字体等），
# 让它们照常走 curl_cffi 或默认下载器。
_SKIP_EXT_RE = re.compile(
    r"\.(xml|txt|pdf|docx?|xlsx?|pptx?|zip|rar|7z|jpe?g|png|gif|svg|webp|ico|"
    r"css|js|mjs|json|mp4|mp3|wav|webm|woff2?|ttf|eot|csv|rss|atom)(\?.*)?$",
    re.I,
)


class ScrapyTemplateSpiderMiddleware:
    """Spider 中间件：处理传入 Spider 的 response 及其产出。"""

    @classmethod
    def from_crawler(cls, crawler):
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_spider_input(self, response):
        # 每个经过 Spider 中间件进入 Spider 的 response 都会调用。
        return None

    async def process_spider_output(self, response, result):
        # 处理 Spider 返回的结果（Item / Request）。
        # Scrapy 2.13+ 要求该方法为 async 生成器（统一异步中间件）。
        async for item in result:
            yield item

    def process_spider_exception(self, response, exception):
        # 当 Spider 或 process_spider_input 抛出异常时调用。
        pass

    def spider_opened(self, spider):
        spider.logger.info("Spider 已开启：%s", spider.name)


class ScrapyTemplateDownloaderMiddleware:
    """Downloader 中间件：处理请求发出与响应返回。"""

    def __init__(self, ssrf_protection_enabled=True, ssrf_allowed_hosts=None):
        self.ssrf_protection_enabled = bool(ssrf_protection_enabled)
        self.ssrf_allowed_hosts = tuple(
            str(host).strip().lower() for host in ssrf_allowed_hosts or () if str(host).strip()
        )

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        s = cls(
            ssrf_protection_enabled=settings.getbool("SSRF_PROTECTION_ENABLED", True),
            ssrf_allowed_hosts=settings.getlist("SSRF_ALLOWED_HOSTS", []),
        )
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_request(self, request):
        if self.ssrf_protection_enabled and self._is_blocked_url(request.url):
            raise IgnoreRequest(f"blocked_ssrf_target: {request.url}")
        return None

    def process_response(self, request, response):
        # 处理下载器返回的 response。
        return response

    def process_exception(self, request, exception):
        # 当下载处理或 process_request 抛出异常时调用。
        pass

    def spider_opened(self, spider):
        spider.logger.info("Spider 已开启：%s", spider.name)

    def _is_blocked_url(self, url):
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().lower()
        if not host or self._host_allowed(host):
            return False
        return any(self._blocked_ip(address) for address in self._resolve_host(host))

    def _host_allowed(self, host):
        return any(fnmatch.fnmatchcase(host, pattern) for pattern in self.ssrf_allowed_hosts)

    @staticmethod
    def _resolve_host(host):
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        try:
            return {
                ipaddress.ip_address(result[4][0])
                for result in socket.getaddrinfo(host, None)
            }
        except OSError:
            return []

    @staticmethod
    def _blocked_ip(address):
        return (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_unspecified
            or address.is_reserved
            or address.is_multicast
        )


class CurlCffiDownloaderMiddleware:
    """命中 ``CURL_CFFI_HOSTS`` 的主机改用 curl_cffi 的 Chrome 指纹请求。

    部分站点（Cloudflare / Akamai 等）按 TLS ClientHello 指纹（JA3）拦截请求：同一
    URL、同一 headers，用 Twisted/``ssl`` 发会 403/412，用浏览器指纹发则 200。这些
    站点走普通 Downloader 永远 403，本中间件在下载前拦截，用 ``curl_cffi`` 在线程里
    以 Chrome 指纹重新请求，并把结果包成 ``HtmlResponse`` 直接返回给 Spider。

    优先级设在 SSRF 中间件（543）之后（数值更小、更靠近下载器），确保 SSRF 防护先
    于 curl_cffi 生效。仅在请求主机命中白名单时启用，其余请求照常走默认下载器。
    """

    def __init__(self, hosts, concurrency_per_host=2, delay_seconds=0.5):
        self.hosts = tuple(str(h).strip().lower() for h in hosts or () if str(h).strip())
        self.concurrency_per_host = max(1, int(concurrency_per_host))
        self.delay_seconds = float(delay_seconds)
        # curl_cffi 在 process_request 里直接返回 Response，绕过了下载器的
        # CONCURRENT_REQUESTS_PER_DOMAIN / DOWNLOAD_DELAY 节流，这里自建 per-host 信号量
        # 与最小间隔，避免对同一主机瞬间并发过多导致被 WAF/代理重置连接。
        self._semaphores = {}
        self._last_request_at = {}
        self._guard = asyncio.Lock()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            crawler.settings.getlist("CURL_CFFI_HOSTS", []),
            concurrency_per_host=crawler.settings.getint("CURL_CFFI_CONCURRENCY_PER_HOST", 2),
            delay_seconds=crawler.settings.getfloat("CURL_CFFI_DELAY_SECONDS", 0.5),
        )

    async def _semaphore_for(self, host):
        async with self._guard:
            if host not in self._semaphores:
                self._semaphores[host] = asyncio.Semaphore(self.concurrency_per_host)
            return self._semaphores[host]

    async def process_request(self, request):
        if not self.hosts:
            return None
        host = (urlparse(request.url).hostname or "").strip().lower()
        if not host or not self._host_allowed(host):
            return None
        sem = await self._semaphore_for(host)
        async with sem:
            # 同一主机最小间隔，防止瞬时并发把 fake-IP 代理/目标 WAF 打崩。
            if self.delay_seconds > 0:
                async with self._guard:
                    now = asyncio.get_event_loop().time()
                    last = self._last_request_at.get(host, 0.0)
                    wait = self.delay_seconds - (now - last)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._last_request_at[host] = asyncio.get_event_loop().time()
            return await asyncio.to_thread(self._curl_fetch, request)

    def _host_allowed(self, host):
        return any(fnmatch.fnmatchcase(host, pattern) for pattern in self.hosts)

    @staticmethod
    def _curl_fetch(request):
        import logging

        logger = logging.getLogger(__name__)
        try:
            result = curl_get(request.url, timeout=30.0)
        except Exception as exc:  # 网络层失败：返回 503 让 RetryMiddleware 按策略重试
            logger.warning("curl_cffi fetch failed for %s: %r", request.url, exc)
            request.meta["curl_cffi_error"] = str(exc)[:120]
            return HtmlResponse(
                url=request.url,
                status=503,
                body=b"",
                request=request,
                encoding="utf-8",
            )
        return HtmlResponse(
            url=result.url,
            status=result.status,
            headers=result.headers,
            body=result.body,
            request=request,
            encoding=result.encoding,
        )


class PlaywrightRenderMiddleware:
    """命中 ``PLAYWRIGHT_HOSTS`` 的主机用 Playwright 真实浏览器渲染。

    curl_cffi 的 Chrome 指纹只能绕过「按 TLS 指纹拦截」的站；对「必须跑 JS 才能拿到
    正文」的站（瑞数 412、Incapsula 挑战、Cloudflare「Just a moment」、纯 JS SPA 壳）
    仍拿不到内容。这类站对真实浏览器本来就放行，本中间件在下载前用真实无头浏览器执行
    挑战 JS、等它自动重载，把渲染后的 HTML 包成 ``HtmlResponse`` 返回给 spider。

    优先级设在 curl_cffi（530）之前（数值更大、更早执行）、SSRF（543）之后，确保 SSRF
    防护先于 Playwright 生效、且 HTML 页优先走 Playwright、XML/附件照常回落给 curl_cffi。
    """

    def __init__(self, hosts, concurrency_per_host=1, channel="chrome"):
        self.hosts = tuple(str(h).strip().lower() for h in hosts or () if str(h).strip())
        self.concurrency_per_host = max(1, int(concurrency_per_host))
        self._renderer = PlaywrightRenderer(channel=channel)
        self._semaphores = {}
        self._guard = asyncio.Lock()

    @classmethod
    def from_crawler(cls, crawler):
        mw = cls(
            crawler.settings.getlist("PLAYWRIGHT_HOSTS", []),
            concurrency_per_host=crawler.settings.getint("PLAYWRIGHT_CONCURRENCY_PER_HOST", 1),
            channel=crawler.settings.get("PLAYWRIGHT_CHANNEL", "chrome"),
        )
        crawler.signals.connect(mw.spider_closed, signal=signals.spider_closed)
        return mw

    async def _semaphore_for(self, host):
        async with self._guard:
            if host not in self._semaphores:
                self._semaphores[host] = asyncio.Semaphore(self.concurrency_per_host)
            return self._semaphores[host]

    async def process_request(self, request):
        if not self.hosts:
            return None
        host = (urlparse(request.url).hostname or "").strip().lower()
        if not host or not self._host_allowed(host):
            return None
        if _SKIP_EXT_RE.search(urlparse(request.url).path):
            return None
        sem = await self._semaphore_for(host)
        async with sem:
            try:
                result = await self._renderer.render(request.url)
            except Exception as exc:  # noqa: BLE001 - 渲染失败回落给默认下载器/RetryMiddleware
                logging.getLogger(__name__).warning(
                    "Playwright 渲染失败 %s：%r", request.url, exc
                )
                return None
        return HtmlResponse(
            url=result["url"],
            status=200,
            body=result["html"].encode("utf-8"),
            request=request,
            encoding="utf-8",
        )

    def _host_allowed(self, host):
        return any(fnmatch.fnmatchcase(host, pattern) for pattern in self.hosts)

    async def spider_closed(self, spider):  # noqa: ARG002 - 信号回调签名约定
        await self._renderer.close()


class RotatingProxyMiddleware:
    """Use a sticky proxy per host and rotate it after retryable failures."""

    def __init__(self, proxies, max_attempts=3):
        self.proxies = list(proxies)
        self.max_attempts = max(1, int(max_attempts))
        self.host_indexes = {}
        self.next_index = 0

    @classmethod
    def from_crawler(cls, crawler):
        raw_pool = os.getenv("CRAWLER_PROXY_POOL", "").strip()
        if not raw_pool:
            raw_pool = str(crawler.settings.get("CRAWLER_PROXY_POOL", "")).strip()
        proxies = [
            value.strip()
            for value in re.split(r"[\r\n,;]+", raw_pool)
            if value.strip().startswith(("http://", "https://"))
        ]
        if not proxies:
            raise NotConfigured("CRAWLER_PROXY_POOL is not configured")
        crawler.spider.logger.info("Rotating proxy pool enabled: %s proxies", len(proxies))
        return cls(
            proxies,
            max_attempts=crawler.settings.getint("CRAWLER_PROXY_MAX_ATTEMPTS", 3),
        )

    def process_request(self, request):
        if request.meta.get("proxy"):
            return None
        host = (urlparse(request.url).hostname or "").lower()
        if host not in self.host_indexes:
            self.host_indexes[host] = self.next_index % len(self.proxies)
            self.next_index += 1
        base_index = self.host_indexes[host]
        attempt = int(request.meta.get("proxy_attempt", 0) or 0)
        request.meta["proxy"] = self.proxies[(base_index + attempt) % len(self.proxies)]
        request.meta["proxy_base_index"] = base_index
        request.meta["proxy_attempt"] = attempt
        return None

    def process_response(self, request, response):
        if response.status not in PROXY_RETRY_STATUSES:
            return response
        retry = self._retry_request(request)
        return retry if retry is not None else response

    def process_exception(self, request, exception):
        return self._retry_request(request)

    def _retry_request(self, request):
        if not request.meta.get("proxy"):
            return None
        attempt = int(request.meta.get("proxy_attempt", 0) or 0)
        if attempt + 1 >= min(self.max_attempts, len(self.proxies)):
            return None
        base_index = int(request.meta.get("proxy_base_index", 0) or 0)
        next_attempt = attempt + 1
        self.host_indexes[(urlparse(request.url).hostname or "").lower()] = (
            base_index + next_attempt
        ) % len(self.proxies)
        meta = dict(request.meta)
        meta["proxy"] = self.proxies[(base_index + next_attempt) % len(self.proxies)]
        meta["proxy_attempt"] = next_attempt
        return request.replace(dont_filter=True, priority=request.priority + 1, meta=meta)
