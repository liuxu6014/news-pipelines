"""curl_cffi 传输层：用 Chrome 的 TLS/HTTP2 指纹请求被 WAF 指纹拦截的站点。

部分站点（Cloudflare / Akamai 等）会按 TLS ClientHello 指纹（JA3）拦截请求：同样的
URL、同样的 headers，用 Python ``ssl``/Twisted 发会 403/412，用浏览器指纹发则 200。
这类站点用普通 Scrapy Downloader 永远 403，只能用 ``curl_cffi`` 的 ``impersonate``
伪装成 Chrome 重新请求。

本模块只做「带浏览器指纹的同步 HTTP GET」，不涉及 Spider / Pipeline / 调度，属于
可复用运行逻辑（``app/runtime/``）。网络调用是阻塞的，调用方应放到线程里执行。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CurlResult:
    """一次 curl_cffi 请求的结果（bytes 便于直接构造 Scrapy Response）。"""

    status: int
    url: str
    body: bytes
    headers: dict[str, str]
    encoding: str


def curl_get(url, *, timeout: float = 30.0, headers=None, impersonate: str = "chrome",
             interface: str | None = "0.0.0.0") -> CurlResult:
    """用 Chrome 指纹同步 GET ``url``，返回状态码、最终 URL、字节体与响应头。

    ``interface="0.0.0.0"`` 强制 IPv4：在 fake-IP 代理（Clash 等）环境下，IPv6 伪造
    地址（``fdfe::``）常不能被正确路由，导致 TLS 握手被服务端重置（SSL_ERROR_SYSCALL），
    绑 IPv4 源地址可让 libcurl 只用 IPv4。
    """
    from curl_cffi import requests as curl_requests

    resp = curl_requests.get(
        url,
        impersonate=impersonate,
        timeout=timeout,
        headers=headers or {},
        allow_redirects=True,
        interface=interface,
    )
    encoding = getattr(resp, "encoding", None) or "utf-8"
    # curl_cffi 已自动解压 body，但原响应头仍带 Content-Encoding；这里剥掉解压相关头，
    # 否则 Scrapy 的 HttpCompressionMiddleware 会二次解压报错。
    headers = {
        str(k): str(v)
        for k, v in resp.headers.items()
        if str(k).lower() not in {"content-encoding", "content-length", "transfer-encoding"}
    }
    return CurlResult(
        status=resp.status_code,
        url=str(resp.url),
        body=bytes(resp.content),
        headers=headers,
        encoding=encoding,
    )
