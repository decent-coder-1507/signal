"""Local Telegram long polling (§16.6: webhooks need HTTPS; locally we poll). Run:
uv run python -m signal_core.notify.telegram_poll
"""

from __future__ import annotations

import asyncio

from signal_core.db.session import session_scope
from signal_core.logging import configure_logging, get_logger
from signal_core.notify.telegram import client, handle_update

log = get_logger("telegram_poll")


async def main() -> None:
    configure_logging()
    c = client()
    offset = 0
    while True:
        try:
            res = await c.call(
                "getUpdates", offset=offset, timeout=30, allowed_updates=["message", "callback_query"]
            )
            for upd in res.get("result", []) or []:
                offset = max(offset, int(upd["update_id"]) + 1)
                async with session_scope() as s:
                    await handle_update(s, upd)
        except Exception as e:
            log.warning("poll_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
