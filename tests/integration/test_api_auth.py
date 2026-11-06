from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app

EMAIL, PW = "owner@test.local", "correct horse battery"


@pytest.fixture
async def client(seeded: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts

    _attempts.clear()
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def login(c: httpx.AsyncClient) -> str:
    r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code == 200, r.text
    return str(r.json()["csrf"])


async def test_health_green(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["checks"]["db"] == "ok" and body["mode"] == "mock"


async def test_login_and_me(client: httpx.AsyncClient) -> None:
    assert (await client.get("/me")).status_code == 401
    await login(client)
    me = (await client.get("/me")).json()
    assert me["email"] == EMAIL and me["onboarded"] is False


async def test_wrong_password_then_lockout(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": EMAIL, "password": "nope"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code == 401 and "locked" in r.json()["detail"]


async def test_csrf_required_for_cookie_writes(client: httpx.AsyncClient) -> None:
    csrf = await login(client)
    r = await client.put("/settings", json={"quiet_hours": ["23:00", "07:00"]})
    assert r.status_code == 403
    r = await client.put(
        "/settings", json={"quiet_hours": ["23:00", "07:00"]}, headers={"x-csrf-token": csrf}
    )
    assert r.status_code == 200 and r.json()["quiet_hours"] == ["23:00", "07:00"]


async def test_feature_flags_merge(client: httpx.AsyncClient) -> None:
    csrf = await login(client)
    r = await client.put(
        "/settings", json={"flags": {"channel.telegram": True}}, headers={"x-csrf-token": csrf}
    )
    flags = r.json()["flags"]
    assert flags["channel.telegram"] is True and flags["engine.radar"] is True


async def test_api_token_auth_skips_csrf(client: httpx.AsyncClient) -> None:
    csrf = await login(client)
    token = (
        await client.post("/auth/api-token", json={"password": PW}, headers={"x-csrf-token": csrf})
    ).json()["token"]
    client.cookies.clear()
    r = await client.get("/me", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 200
    bad = await client.get("/me", headers={"authorization": "Bearer sig_wrong"})
    assert bad.status_code == 401


async def test_llm_ping_writes_ledger(client: httpx.AsyncClient) -> None:
    csrf = await login(client)
    r = await client.post("/ops/llm-ping?message=yo", headers={"x-csrf-token": csrf})
    assert r.status_code == 200 and r.json()["answer"] == "pong: yo"


async def test_profile_update_bumps_version_and_vectors(client: httpx.AsyncClient) -> None:
    csrf = await login(client)
    p = (await client.get("/profile")).json()
    r = await client.put("/profile", json={"role": "Senior AI Engineer"}, headers={"x-csrf-token": csrf})
    assert r.json()["role"] == "Senior AI Engineer" and r.json()["version"] == p["version"] + 1


async def test_voice_edit_creates_new_version(client: httpx.AsyncClient) -> None:
    csrf = await login(client)
    v1 = (await client.get("/voice")).json()
    r = await client.put(
        "/voice",
        json={"banned_phrases": [*v1["banned_phrases"], "paradigm shift"], "note": "added phrase"},
        headers={"x-csrf-token": csrf},
    )
    v2 = r.json()
    assert v2["version"] == v1["version"] + 1 and "paradigm shift" in v2["banned_phrases"]
    hist = (await client.get("/voice")).json()["history"]
    assert [h["version"] for h in hist] == [1, 2]


async def test_credential_changes_require_reauth_and_session(client: httpx.AsyncClient) -> None:
    import pyotp

    csrf = await login(client)
    h = {"x-csrf-token": csrf}
    assert (await client.post("/auth/api-token", json={"password": "wrong"}, headers=h)).status_code == 403
    token = (await client.post("/auth/api-token", json={"password": PW}, headers=h)).json()["token"]
    # Enable TOTP
    secret = (await client.post("/auth/totp/setup", json={"password": PW}, headers=h)).json()["secret"]
    code = pyotp.TOTP(secret).now()
    r = await client.post(
        "/auth/totp/setup", json={"password": PW, "secret": secret, "code": code}, headers=h
    )
    assert r.json()["enabled"] is True
    # Replacing 2FA without the current code is refused
    r = await client.post("/auth/totp/setup", json={"password": PW}, headers=h)
    assert r.status_code == 403 and "authenticator" in r.json()["detail"]
    # The API token can never change credentials
    client.cookies.clear()
    r = await client.post(
        "/auth/api-token", json={"password": PW}, headers={"authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403 and "session required" in r.json()["detail"]
