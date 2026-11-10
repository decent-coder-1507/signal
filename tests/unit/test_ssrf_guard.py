import httpx
import pytest
import respx

from signal_core.sources.http import BlockedURL, PoliteClient, _ip_is_public, assert_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8710/health",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://x",
    ],
)
async def test_internal_and_non_http_urls_are_blocked(url: str) -> None:
    with pytest.raises(BlockedURL):
        await assert_public_url(url)


async def test_public_ip_literal_passes() -> None:
    await assert_public_url("https://1.1.1.1/")


@respx.mock
async def test_redirect_to_internal_address_is_blocked() -> None:
    respx.get("https://93.184.215.14/start").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    )
    c = PoliteClient(per_host_interval_s=0, retries=0, guard=True)
    try:
        with pytest.raises(BlockedURL):
            await c.get("https://93.184.215.14/start")
    finally:
        await c.aclose()


@respx.mock
async def test_public_redirect_is_followed_with_guard() -> None:
    respx.get("https://93.184.215.14/a").mock(return_value=httpx.Response(301, headers={"location": "/b"}))
    respx.get("https://93.184.215.14/b").mock(return_value=httpx.Response(200, text="ok"))
    c = PoliteClient(per_host_interval_s=0, retries=0, guard=True)
    try:
        r = await c.get("https://93.184.215.14/a")
        assert r.status_code == 200 and r.text == "ok"
    finally:
        await c.aclose()


def test_nat64_addresses_are_judged_by_their_embedded_ipv4() -> None:
    # IPv6-only networks (DNS64/NAT64) resolve public sites to 64:ff9b::<ipv4>; internal IPv4s stay blocked.
    assert _ip_is_public("64:ff9b::14cf:4952")  # 20.207.73.82 (github.com)
    assert not _ip_is_public("64:ff9b::a00:1")  # 10.0.0.1
    assert not _ip_is_public("64:ff9b::7f00:1")  # 127.0.0.1
    assert not _ip_is_public("64:ff9b:1::a00:1")  # local-use NAT64 prefix: layout not fixed, stays blocked


@respx.mock
async def test_not_modified_is_not_followed_as_a_redirect() -> None:
    # httpx reports 304 as a redirect; following it looped until "too many redirects" and failed the source.
    respx.get("https://93.184.215.14/feed").mock(return_value=httpx.Response(304))
    async with PoliteClient(guard=True) as c:
        r = await c.get("https://93.184.215.14/feed", etag='W/"abc"')
    assert r.status_code == 304
