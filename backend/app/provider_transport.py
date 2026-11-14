"""Outbound HTTP transport for provider (Gmail / Microsoft Graph) calls.

Server deployments behind a restricted egress network can reach the internal
WhatsApp bridge but not ``login.microsoftonline.com`` / ``graph.microsoft.com``.
Without an explicit proxy every provider call fails with a generic "cannot
connect" error, which is indistinguishable from an expired credential in the
operator UI. This module centralises transport construction so a deployment can
set ``PROVIDER_HTTPS_PROXY`` once and have every provider client honour it.

When no provider proxy is configured ``httpx`` keeps its default behaviour
(``trust_env=True``), so an existing container-wide ``HTTPS_PROXY`` still works.
"""

from __future__ import annotations

import os
import socket
import ssl

import httpx

PROXY_ENV_KEYS = ("PROVIDER_HTTPS_PROXY", "PROVIDER_HTTP_PROXY", "PROVIDER_ALL_PROXY")

NETWORK_FAILURE_LABELS = {
    "dns": "域名解析失败（DNS）",
    "timeout": "连接超时",
    "refused": "连接被拒绝",
    "tls": "TLS 握手失败",
    "proxy": "代理连接失败",
    "connect": "无法建立 TCP 连接",
    "network": "网络错误",
}

NETWORK_FAILURE_HINTS = {
    "dns": "backend 容器无法解析 provider 域名，请检查容器 DNS 配置（可加 --dns 8.8.8.8 或内网 DNS）。",
    "timeout": "出站 443 可能被限制或代理未生效，请放通白名单或配置 PROVIDER_HTTPS_PROXY。",
    "refused": "provider 拒绝连接，请检查出站防火墙、代理端口与代理存活状态。",
    "tls": "TLS 握手失败，多为出口被中间设备拦截或容器系统时间偏差过大。",
    "proxy": "代理不可用，请检查 PROVIDER_HTTPS_PROXY 的地址、端口与账号密码。",
    "connect": "无法建立到 provider 的 TCP 连接，请放通出站 443 或配置 PROVIDER_HTTPS_PROXY。",
    "network": "出站网络异常，请检查容器网络、DNS 与代理配置。",
}


def classify_network_failure(exc: BaseException) -> dict[str, str]:
    """Turn an outbound transport error into a fixed, non-sensitive diagnosis.

    Only the exception class, the failing host, and an OS error category are
    reported. No request data, token, or response body is exposed.
    """
    host = ""
    request = getattr(exc, "request", None)
    if request is not None:
        url = getattr(request, "url", None)
        if url is not None:
            host = url.host or ""

    kind = "network"
    if isinstance(exc, httpx.ProxyError):
        kind = "proxy"
    elif isinstance(exc, httpx.TimeoutException):
        kind = "timeout"
    elif isinstance(exc, httpx.ConnectError):
        kind = "connect"
        cause: BaseException | None = exc.__cause__
        seen: set[int] = set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, socket.gaierror):
                kind = "dns"
                break
            if isinstance(cause, ConnectionRefusedError):
                kind = "refused"
                break
            if isinstance(cause, ssl.SSLError):
                kind = "tls"
                break
            cause = cause.__cause__
    elif isinstance(exc, ssl.SSLError):
        kind = "tls"

    return {
        "kind": kind,
        "label": NETWORK_FAILURE_LABELS[kind],
        "host": host,
        "error_class": type(exc).__name__,
        "hint": NETWORK_FAILURE_HINTS[kind],
    }


def network_failure_message(exc: BaseException, *, target: str) -> str:
    """Operator-facing sentence for a failed provider call."""
    detail = classify_network_failure(exc)
    host = f"（{detail['host']}）" if detail["host"] else ""
    return f"无法连接 {target}{host}：{detail['label']}。{detail['hint']}"


def provider_proxy() -> str | None:
    """Return the configured provider proxy URL, if any."""
    for key in PROXY_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def provider_proxy_summary() -> str:
    """Human-readable, non-sensitive description of the egress configuration."""
    if provider_proxy():
        return "已配置 provider 出站代理（PROVIDER_*_PROXY）"
    if os.environ.get("HTTPS_PROXY", "").strip() or os.environ.get("https_proxy", "").strip():
        return "未单独配置 provider 代理，将沿用容器级 HTTPS_PROXY"
    return "未配置代理，直连 provider（需要放通出站 443）"


def provider_http_client(
    timeout: float = 20.0,
    *,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Build the HTTP client used for provider token and API calls.

    A dedicated proxy disables ``trust_env`` so container-level ``NO_PROXY``
    entries cannot silently bypass the explicitly configured provider proxy.
    """
    proxy = provider_proxy()
    if transport is not None:
        return httpx.Client(timeout=timeout, transport=transport)
    if proxy:
        return httpx.Client(timeout=timeout, proxy=proxy, trust_env=False)
    return httpx.Client(timeout=timeout)
