"""Polite HTTP client (§6.2): generic UA (no personal data), per-host spacing, global concurrency cap,
conditional GET (ETag/Last-Modified), exponential backoff, robots.txt for HTML fetches.

Measured at build time (ADR-012): this host's network drops connections when ~60 requests run at once,
so the default global concurrency is 6 with a 45 s timeout and 2 retries.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "SIGNAL/0.1 (personal news reader; single user; respects robots.txt)"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_REDIRECTS = 5


class BlockedURL(PermissionError):
    """URL rejected by the SSRF guard (non-http scheme, or a host resolving to a private/internal address)."""


def _ip_is_public(ip: str) -> bool:
    a: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    internal = (
        a.is_private
        or a.is_loopback
        or a.is_link_local
        or a.is_multicast
        or a.is_reserved
        or a.is_unspecified
    )
    if isinstance(a, ipaddress.IPv6Address):
        internal = internal or a.is_site_local
    return not internal


async def assert_public_url(url: str) -> None:
    """SSRF guard: http(s) only and every resolved address must be public (checked on each redirect hop).
    Residual risk: DNS rebinding between this check and the connect (single-user app; documented in ADR-017)."""
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BlockedURL(f"only http(s) URLs are allowed: {url!r}")
    host = p.hostname
    try:
        infos = (
            [host]
            if _is_ip(host)
            else [
                i[4][0]
                for i in await asyncio.get_running_loop().getaddrinfo(
                    host, p.port or 443, type=socket.SOCK_STREAM
                )
            ]
        )
    except socket.gaierror as e:
        raise BlockedURL(f"cannot resolve host {host!r}") from e
    bad = [ip for ip in map(str, infos) if not _ip_is_public(ip)]
    if bad:
        raise BlockedURL(f"{host} resolves to a non-public address ({bad[0]})")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


class PoliteClient:
    def __init__(
        self,
        *,
        concurrency: int = 6,
        per_host_interval_s: float = 1.0,
        timeout_s: float = 45.0,
        retries: int = 2,
        backoff_s: float = 1.5,
        transport: httpx.AsyncBaseTransport | None = None,
        guard: bool | None = None,
    ) -> None:
        from signal_core.settings import get_settings

        # The SSRF guard applies to real network access; injected transports (fixtures, tests) are in-process.
        self.guard = (transport is None and get_settings().ssrf_guard) if guard is None else guard
        self._client = httpx.AsyncClient(
            headers={"user-agent": USER_AGENT, "accept-encoding": "gzip, deflate"},
            timeout=timeout_s,
            follow_redirects=not self.guard,  # with the guard on, every redirect hop is re-validated
            transport=transport,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._host_last: dict[str, float] = {}
        self.per_host_interval_s = per_host_interval_s
        self.retries = retries
        self.backoff_s = backoff_s
        self._robots: dict[str, RobotFileParser | None] = {}
        # arXiv API asks for ≤1 request / 3 s; the HN Firebase API has no published rate limit.
        self.host_intervals: dict[str, float] = {"export.arxiv.org": 3.0, "hacker-news.firebaseio.com": 0.1}

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _space(self, host: str) -> None:
        interval = self.host_intervals.get(host, self.per_host_interval_s)
        async with self._host_locks[host]:
            wait = self._host_last.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_last[host] = time.monotonic()

    async def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                r = await self._client.get(base + "/robots.txt", timeout=10)
                if r.status_code >= 400:
                    rp = None  # no robots.txt → allowed
                else:
                    assert rp is not None
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        html: bool = False,
        timeout: float | None = None,
    ) -> httpx.Response:
        if self.guard:
            await assert_public_url(url)
        if html and not await self.allowed_by_robots(url):
            raise PermissionError(f"robots.txt disallows {url}")
        if self.guard:
            return await self._get_validated(
                url, params=params, headers=headers, etag=etag, last_modified=last_modified, timeout=timeout
            )
        return await self._get(
            url, params=params, headers=headers, etag=etag, last_modified=last_modified, timeout=timeout
        )

    async def _get_validated(self, url: str, **kw: Any) -> httpx.Response:
        for _ in range(MAX_REDIRECTS + 1):
            resp = await self._get(url, **kw)
            if not resp.is_redirect:
                return resp
            url = urljoin(url, resp.headers.get("location", ""))
            await assert_public_url(url)
            kw["params"] = None
        raise BlockedURL(f"too many redirects ({MAX_REDIRECTS})")

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        h = dict(headers or {})
        if etag:
            h["if-none-match"] = etag
        if last_modified:
            h["if-modified-since"] = last_modified
        host = urlsplit(url).netloc
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            async with self._sem:
                await self._space(host)
                try:
                    kw: dict[str, Any] = {"params": params, "headers": h}
                    if timeout is not None:
                        kw["timeout"] = timeout
                    resp = await self._client.get(url, **kw)
                    if resp.status_code not in RETRY_STATUS or attempt == self.retries:
                        return resp
                    last_exc = httpx.HTTPStatusError(
                        f"{resp.status_code}", request=resp.request, response=resp
                    )
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    last_exc = e
                    if attempt == self.retries:
                        raise
            await asyncio.sleep(self.backoff_s * (2**attempt) * (0.75 + random.random() / 2))
        assert last_exc is not None
        raise last_exc

    async def post(self, url: str, **kw: Any) -> httpx.Response:
        if self.guard:
            await assert_public_url(url)
        async with self._sem:
            await self._space(urlsplit(url).netloc)
            return await self._client.post(url, **kw)
