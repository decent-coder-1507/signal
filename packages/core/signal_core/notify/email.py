"""Email digests (§14): daily (optional), weekly and monthly, as clean HTML with links back to the app.

Transport: SMTP (`SIGNAL_SMTP_URL=smtp(s)://user:pass@host:port`). In mock mode, or without SMTP, messages are
written to `<data_dir>/outbox/*.eml` so they can be inspected and tested without sending anything.
"""

from __future__ import annotations

import asyncio
import html
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from signal_core.settings import get_settings

STYLE = (
    "font-family:-apple-system,Segoe UI,Inter,sans-serif;max-width:640px;margin:auto;color:#1c1b19;"
    "line-height:1.5"
)


def _li(title: str, href: str, sub: str = "") -> str:
    return (
        f'<li style="margin:0 0 12px"><a href="{html.escape(href)}" style="color:#b45309">{html.escape(title)}</a>'
        + (f'<br><span style="color:#6b6862;font-size:14px">{html.escape(sub)}</span>' if sub else "")
        + "</li>"
    )


def render(kind: str, payload: dict[str, Any]) -> tuple[str, str]:
    app = get_settings().web_origin
    c = payload.get("content", payload)
    if kind == "brief":
        subject = f"SIGNAL brief: {c.get('topline') or str(len(c.get('stories', []))) + ' stories'}"[:150]
        items = "".join(
            _li(s["title"], f"{app}/stories/{s['story_id']}", s.get("why_you") or "")
            for s in c.get("stories", [])
        )
        body = (
            f"<h1 style='font-size:22px'>{html.escape(c.get('topline') or 'Your brief')}</h1><ol>{items}</ol>"
            f"<p><a href='{app}/brief'>Open the brief</a></p>"
        )
    elif kind in ("weekly", "monthly"):
        subject = f"SIGNAL {kind} review"
        sections = "".join(
            f"<h2 style='font-size:18px'>{html.escape(sec['title'])}</h2>"
            + (f"<p>{html.escape(sec['text'])}</p>" if sec.get("text") else "")
            + (
                "<ul>"
                + "".join(_li(x["title"], x.get("href", app), x.get("sub", "")) for x in sec.get("items", []))
                + "</ul>"
                if sec.get("items")
                else ""
            )
            for sec in c.get("sections", [])
        )
        body = f"<h1 style='font-size:22px'>{subject}</h1>{sections}<p><a href='{app}/reviews'>Open the review</a></p>"
    else:
        subject = f"SIGNAL: {kind}"
        body = f"<p>{html.escape(str(payload.get('text', '')))}</p>"
    return subject, f"<!doctype html><html><body style='{STYLE}'>{body}</body></html>"


def _smtp_send(url: str, msg: EmailMessage) -> None:
    u = urlsplit(url)
    port = u.port or (465 if u.scheme == "smtps" else 587)
    if u.scheme == "smtps":
        server: smtplib.SMTP = smtplib.SMTP_SSL(u.hostname or "", port, timeout=30)
    else:
        server = smtplib.SMTP(u.hostname or "", port, timeout=30)
        server.starttls()
    with server:
        if u.username:
            server.login(unquote(u.username), unquote(u.password or ""))
        server.send_message(msg)


async def send_digest(kind: str, payload: dict[str, Any]) -> Path | None:
    s = get_settings()
    subject, body = render(kind, payload)
    msg = EmailMessage()
    msg["Subject"], msg["From"] = subject, s.email_from
    msg["To"] = payload.get("to") or s.admin_email
    msg.set_content("Open in an HTML-capable client.")
    msg.add_alternative(body, subtype="html")
    if s.smtp_url and not s.is_mock:
        await asyncio.to_thread(_smtp_send, s.smtp_url, msg)
        return None
    out = s.data_dir / "outbox"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}-{kind}.eml"
    path.write_bytes(bytes(msg))
    return path
