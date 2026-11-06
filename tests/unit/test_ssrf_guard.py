import httpx
import pytest
import respx

from signal_core.sources.http import BlockedURL, PoliteClient, assert_public_url


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
