"""Telegram bot (§10.2, §14): brief summary with inline feedback buttons, commands, card mini-sessions, ask-me,
publish-assist, metrics forms (M9), capture by forwarding links/text.

Security: only the configured chat id is served (allowlist); webhooks must carry the secret header
(X-Telegram-Bot-Api-Secret-Token). Local mode uses long polling (`python -m signal_core.notify.telegram_poll`).
Bot API methods used (stable for years, verified against core.telegram.org/bots/api): sendMessage (+ reply_markup
inline_keyboard), editMessageText, answerCallbackQuery, getUpdates.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Brief, Card, Draft, Idea, Story
from signal_core.logging import get_logger
from signal_core.settings import get_settings

log = get_logger("telegram")
_transport: httpx.AsyncBaseTransport | None = None  # tests inject a mock Telegram server
URL_RX = re.compile(r"https?://\S+")


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = t


class TelegramClient:
    def __init__(self, token: str, api_base: str = "https://api.telegram.org") -> None:
        self.base = f"{api_base.rstrip('/')}/bot{token}"

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=_transport, timeout=40) as c:
            r = await c.post(f"{self.base}/{method}", json={k: v for k, v in params.items() if v is not None})
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return (
            dict(data.get("result") or {})
            if isinstance(data.get("result"), dict)
            else {"result": data.get("result")}
        )

    async def send(
        self, chat_id: str, text: str, buttons: list[list[dict[str, str]]] | None = None
    ) -> dict[str, Any]:
        markup = {"inline_keyboard": buttons} if buttons else None
        return await self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text[:4096],
            reply_markup=markup,
            disable_web_page_preview=True,
        )


def client() -> TelegramClient:
    s = get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("SIGNAL_TELEGRAM_BOT_TOKEN not set")
    return TelegramClient(s.telegram_bot_token, s.telegram_api_base)


def brief_message(content: dict[str, Any], app_url: str) -> tuple[str, list[list[dict[str, str]]]]:
    stories = content.get("stories", [])
    head = {"catchup": "While you were away", "weekend": "Weekend brief"}.get(
        content.get("kind", ""), "Your brief"
    )
    lines = [f"{head}: {len(stories)} stories"]
    if content.get("topline"):
        lines.append(content["topline"])
    extras = [
        x
        for x, k in (
            ("1 post suggestion", "post_suggestion"),
            ("1 build spark", "build_spark"),
            ("1 learn item", "learn"),
        )
        if content.get(k)
    ]
    if content.get("cards_due"):
        extras.append(f"{content['cards_due']} cards to review")
    if extras:
        lines.append(", ".join(extras))
    if content.get("quiet"):
        lines.append(content["quiet"]["message"])
    buttons: list[list[dict[str, str]]] = []
    for i, s in enumerate(stories, 1):
        lines.append(f"\n{i}. {s['title']}")
        sid = s["story_id"]
        buttons.append(
            [
                {"text": f"{i} 👍", "callback_data": f"fb:{sid}:useful"},
                {"text": "👎", "callback_data": f"fb:{sid}:not_for_me"},
                {"text": "Post", "callback_data": f"act:{sid}:post"},
                {"text": "Build", "callback_data": f"act:{sid}:build"},
                {"text": "Learn", "callback_data": f"act:{sid}:learn"},
            ]
        )
    lines.append(f"\nOpen: {app_url}/brief")
    return "\n".join(lines), buttons


async def send_notification(kind: str, payload: dict[str, Any]) -> None:
    s = get_settings()
    c = client()
    chat = str(s.telegram_chat_id)
    if kind == "brief":
        text, buttons = brief_message(payload["content"], s.web_origin)
        await c.send(chat, text, buttons)
    elif kind == "cards":
        await c.send(
            chat,
            f"{payload.get('due', 0)} flashcards due. Review now?",
            [[{"text": "Start (3 cards)", "callback_data": "cards:start"}]],
        )
    elif kind == "publish_assist":
        await c.send(
            chat,
            f"Time to post on {payload['platform']}:\n\n{payload['text']}\n\nComposer: "
            f"{payload.get('composer_url') or ''}",
            [[{"text": "Posted ✓", "callback_data": f"posted:{payload['draft_id']}"}]],
        )
    elif kind == "metrics_prompt":
        await c.send(
            chat,
            f"How did your {payload['platform']} post do ({payload['horizon']})? Reply with:\n"
            f"/metrics {payload['publication_id'].replace('-', '')[-8:]} impressions reactions comments reposts saves",
        )
    else:
        await c.send(chat, payload.get("text") or f"{kind}: {payload.get('title', '')}")


HELP = (
    "Commands: /brief · /post <story#> · /save <url> · /idea <text> · /log <text> · /cards · /ask <question> · "
    "/metrics <id> <impressions> <reactions> <comments> <reposts> <saves>"
)


async def handle_update(session: AsyncSession, update: dict[str, Any]) -> dict[str, Any]:
    """Process one Telegram update. Returns a small summary (useful for tests and logs)."""
    s = get_settings()
    allowed = str(s.telegram_chat_id or "")
    msg = update.get("message") or update.get("edited_message")
    cb = update.get("callback_query")
    chat_id = str((msg or (cb or {}).get("message") or {}).get("chat", {}).get("id", ""))
    if not allowed or chat_id != allowed:
        log.warning("telegram_rejected_chat", chat_id=chat_id)
        return {"ignored": "chat not allowed"}
    c = client()
    if cb:
        return await _callback(session, c, chat_id, cb)
    text = (msg or {}).get("text") or (msg or {}).get("caption") or ""
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    now = datetime.now(UTC)
    if cmd in ("/start", "/help"):
        await c.send(chat_id, f"SIGNAL is connected. {HELP}")
        return {"cmd": "help"}
    if cmd == "/brief":
        b = (await session.execute(select(Brief).order_by(desc(Brief.created_at)).limit(1))).scalars().first()
        if b is None:
            await c.send(chat_id, "No brief yet. It arrives at your scheduled time.")
            return {"cmd": "brief", "found": False}
        t, buttons = brief_message(b.content, s.web_origin)
        await c.send(chat_id, t, buttons)
        return {"cmd": "brief", "found": True}
    if cmd == "/post":
        return await _post_from_brief(session, c, chat_id, arg.strip())
    if cmd == "/save" or (not cmd.startswith("/") and URL_RX.search(text)):
        url = URL_RX.search(arg) or URL_RX.search(text)
        if not url:
            await c.send(chat_id, "Send /save <url>")
            return {"cmd": "save", "ok": False}
        from signal_core.radar.capture import capture_url

        item = await capture_url(session, url.group(0).rstrip(".,)"), intent="read_later")
        await c.send(chat_id, f"Saved: {item.title}")
        return {"cmd": "save", "item_id": str(item.id)}
    if cmd == "/idea":
        if not arg.strip():
            await c.send(chat_id, "Send /idea <text>")
            return {"cmd": "idea", "ok": False}
        idea = Idea(
            type="poc", title=arg.strip()[:200], one_liner=arg.strip(), origin="manual", status="shortlisted"
        )
        session.add(idea)
        await session.flush()
        await c.send(chat_id, f"Idea saved to LAB: {idea.title}")
        return {"cmd": "idea", "idea_id": str(idea.id)}
    if cmd == "/log":
        from signal_core.lab.service import add_log

        building = (
            (
                await session.execute(
                    select(Idea).where(Idea.status == "building").order_by(desc(Idea.updated_at)).limit(1)
                )
            )
            .scalars()
            .first()
        )
        if building is None or not arg.strip():
            await c.send(chat_id, "No building is in 'building', or the log text is empty.")
            return {"cmd": "log", "ok": False}
        await add_log(session, building, arg, at=now)
        await c.send(chat_id, f"Logged to “{building.title}”.")
        return {"cmd": "log", "building_id": str(building.id)}
    if cmd == "/cards":
        return await _next_card(session, c, chat_id, now)
    if cmd == "/ask":
        try:
            from signal_core.ask.service import answer

            res = await answer(session, arg.strip(), thread_id=None)
            await c.send(chat_id, res["answer"][:3500])
            return {"cmd": "ask", "ok": True}
        except ModuleNotFoundError:
            await c.send(chat_id, "Ask SIGNAL is not available yet.")
            return {"cmd": "ask", "ok": False}
    if cmd == "/metrics":
        try:
            from signal_core.analytics.service import metrics_from_text

            out = await metrics_from_text(session, arg)
            await c.send(chat_id, out["message"])
            return {"cmd": "metrics", **out}
        except ModuleNotFoundError:
            await c.send(chat_id, "Metrics logging is not available yet.")
            return {"cmd": "metrics", "ok": False}
    if text and not cmd.startswith("/"):
        from signal_core.radar.capture import capture_text

        item = await capture_text(session, text, intent="read_later")
        await c.send(chat_id, f"Saved as a note: {item.title}")
        return {"cmd": "note", "item_id": str(item.id)}
    await c.send(chat_id, HELP)
    return {"cmd": "unknown"}


async def _post_from_brief(
    session: AsyncSession, c: TelegramClient, chat_id: str, arg: str
) -> dict[str, Any]:
    b = (await session.execute(select(Brief).order_by(desc(Brief.created_at)).limit(1))).scalars().first()
    try:
        idx = int(arg) - 1
        sid = b.content["stories"][idx]["story_id"] if b else None
    except (ValueError, IndexError, TypeError):
        sid = None
    if not sid:
        await c.send(chat_id, "Send /post <story number from today's brief>")
        return {"cmd": "post", "ok": False}
    from signal_core.studio.service import create_angles

    ideas = await create_angles(session, "story", uuid.UUID(sid))
    lines = [f"{i + 1}. [{x.angle_type}] {x.thesis}" for i, x in enumerate(ideas)]
    await c.send(
        chat_id,
        "Angles:\n" + "\n".join(lines),
        [[{"text": f"Draft {i + 1}", "callback_data": f"angle:{x.id}"}] for i, x in enumerate(ideas)],
    )
    return {"cmd": "post", "angles": len(ideas)}


async def _next_card(session: AsyncSession, c: TelegramClient, chat_id: str, now: datetime) -> dict[str, Any]:
    from signal_core.gym.service import due_cards

    due = await due_cards(session, now, limit=1)
    if not due:
        await c.send(chat_id, "No cards due. Nice.")
        return {"cmd": "cards", "due": 0}
    card = due[0]
    await c.send(
        chat_id, f"🃏 {card.front}", [[{"text": "Show answer", "callback_data": f"card:{card.id}:show"}]]
    )
    return {"cmd": "cards", "card_id": str(card.id)}


async def _callback(
    session: AsyncSession, c: TelegramClient, chat_id: str, cb: dict[str, Any]
) -> dict[str, Any]:
    data = str(cb.get("data", ""))
    now = datetime.now(UTC)
    await c.call("answerCallbackQuery", callback_query_id=cb.get("id"))
    parts = data.split(":")
    if parts[0] == "fb" and len(parts) == 3:
        from signal_core.db.models import Feedback

        session.add(
            Feedback(
                target_type="story", target_id=uuid.UUID(parts[1]), kind=parts[2], context={"via": "telegram"}
            )
        )
        await session.flush()
        return {"callback": "feedback", "kind": parts[2]}
    if parts[0] == "act" and len(parts) == 3:
        from signal_core.brief.habit import mark
        from signal_core.db.models import Feedback

        session.add(
            Feedback(
                target_type="story",
                target_id=uuid.UUID(parts[1]),
                kind="used",
                context={"via": "telegram", "action": parts[2]},
            )
        )
        await mark(session, now, "action")
        if parts[2] == "post":
            return await _post_from_story(session, c, chat_id, parts[1])
        await c.send(
            chat_id, f"Noted. Open the app to continue: {get_settings().web_origin}/stories/{parts[1]}"
        )
        return {"callback": "action", "action": parts[2]}
    if parts[0] == "cards" and parts[1] == "start":
        return await _next_card(session, c, chat_id, now)
    if parts[0] == "card" and len(parts) == 3:
        card = await session.get(Card, uuid.UUID(parts[1]))
        if card is None:
            return {"callback": "card", "ok": False}
        if parts[2] == "show":
            await c.send(
                chat_id,
                f"✅ {card.back}",
                [
                    [
                        {"text": "Again", "callback_data": f"card:{card.id}:1"},
                        {"text": "Hard", "callback_data": f"card:{card.id}:2"},
                        {"text": "Good", "callback_data": f"card:{card.id}:3"},
                        {"text": "Easy", "callback_data": f"card:{card.id}:4"},
                    ]
                ],
            )
            return {"callback": "card_show"}
        from signal_core.gym.service import review_card

        await review_card(session, card, int(parts[2]), now)
        nxt = await _next_card(session, c, chat_id, now)
        if nxt.get("due") == 0:
            from signal_core.brief.habit import mark

            await mark(session, now, "cards")
        return {"callback": "card_review", "rating": int(parts[2])}
    if parts[0] == "angle" and len(parts) == 2:
        from signal_core.studio.service import start_drafts

        drafts = await start_drafts(session, uuid.UUID(parts[1]), ["linkedin"])
        d = drafts[0]
        if d.pending_questions:
            await c.send(
                chat_id,
                "Before I draft: "
                + d.pending_questions[0]["question"]
                + f"\nAnswer in the app: {get_settings().web_origin}/studio/drafts/{d.id}",
            )
        else:
            await c.send(chat_id, f"Draft ready for review: {get_settings().web_origin}/studio/drafts/{d.id}")
        return {"callback": "angle", "draft_id": str(d.id)}
    if parts[0] == "posted" and len(parts) == 2:
        posted = await session.get(Draft, uuid.UUID(parts[1]))
        await c.send(
            chat_id,
            f"Paste the post URL in the app to log it: {get_settings().web_origin}/studio/drafts/{parts[1]}",
        )
        return {"callback": "posted", "ok": posted is not None}
    return {"callback": "unknown"}


async def _post_from_story(
    session: AsyncSession, c: TelegramClient, chat_id: str, sid: str
) -> dict[str, Any]:
    from signal_core.studio.service import create_angles

    story = await session.get(Story, uuid.UUID(sid))
    if story is None:
        return {"callback": "post", "ok": False}
    ideas = await create_angles(session, "story", story.id)
    await c.send(
        chat_id,
        "Angles:\n" + "\n".join(f"{i + 1}. [{x.angle_type}] {x.thesis}" for i, x in enumerate(ideas)),
        [[{"text": f"Draft {i + 1}", "callback_data": f"angle:{x.id}"}] for i, x in enumerate(ideas)],
    )
    return {"callback": "post", "angles": len(ideas)}
