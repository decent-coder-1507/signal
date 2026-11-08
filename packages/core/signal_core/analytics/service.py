"""Analytics & learning loop (§7.11): metric prompts (+48 h, +7 d), manual/Telegram/CSV metrics, comparison with the
baseline (median of his last 10 pre-SIGNAL posts), experiments (one variable at a time, with sample-size caution),
monthly learnings (P16) → proposed voice/timing changes → accepted = new voice version."""

from __future__ import annotations

import csv
import io
import re
import statistics
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Experiment, Metric, Publication
from signal_core.llm import router as llm
from signal_core.services.settings_store import get_setting, set_setting

FIELDS = ("impressions", "reactions", "comments", "reposts", "saves", "profile_views", "followers_gained")
HORIZONS = {"48h": timedelta(hours=48), "7d": timedelta(days=7)}
MIN_SAMPLE = 5  # below this, experiment results are reported as "too few posts to say"


def engagement(m: Metric | dict[str, Any]) -> float:
    def g(k: str) -> float:
        v = m.get(k, 0) if isinstance(m, dict) else getattr(m, k, 0)
        return float(v or 0)

    imp = g("impressions")
    inter = g("reactions") + 2 * g("comments") + 2 * g("reposts") + g("saves")
    return round(100 * inter / imp, 3) if imp else 0.0


async def record_metrics(
    session: AsyncSession,
    pub: Publication,
    values: dict[str, int],
    horizon: str = "custom",
    source: str = "manual",
    at: datetime | None = None,
) -> Metric:
    m = Metric(
        publication_id=pub.id,
        captured_at=at or datetime.now(UTC),
        horizon=horizon,
        source=source,
        **{k: int(values.get(k, 0) or 0) for k in FIELDS},
    )
    session.add(m)
    from signal_core.db.models import Draft

    if pub.draft_id:
        d = await session.get(Draft, pub.draft_id)
        if d is not None and horizon in ("48h", "7d"):
            d.status = "measured"
    await session.flush()
    return m


async def due_prompts(session: AsyncSession, now: datetime) -> list[tuple[Publication, str]]:
    pubs = list(
        (
            await session.execute(
                select(Publication).where(
                    Publication.is_baseline.is_(False), Publication.published_at >= now - timedelta(days=9)
                )
            )
        ).scalars()
    )
    out = []
    for p in pubs:
        have = set(
            (await session.execute(select(Metric.horizon).where(Metric.publication_id == p.id))).scalars()
        )
        asked = set((p.variables or {}).get("_prompted", []))
        for h, dt in HORIZONS.items():
            if h not in have and h not in asked and p.published_at + dt <= now:
                out.append((p, h))
    return out


async def send_prompts(session: AsyncSession, now: datetime) -> int:
    from signal_core.notify.dispatcher import dispatch

    n = 0
    for p, h in await due_prompts(session, now):
        payload = {"publication_id": str(p.id), "platform": p.platform, "horizon": h, "url": p.url}
        await dispatch(session, "telegram", "metrics_prompt", payload, now, urgent=False)
        await dispatch(session, "app", "metrics_prompt", payload, now)
        p.variables = {**(p.variables or {}), "_prompted": [*(p.variables or {}).get("_prompted", []), h]}
        n += 1
    await session.flush()
    return n


async def metrics_from_text(session: AsyncSession, text: str) -> dict[str, Any]:
    """Telegram one-line form: '<pub id prefix> impressions reactions comments reposts saves [profile_views followers]'."""
    parts = text.split()
    if len(parts) < 2:
        return {"ok": False, "message": "Send: /metrics <id> impressions reactions comments reposts saves"}
    prefix, nums = parts[0].lower(), parts[1:]
    if not all(re.fullmatch(r"\d+", n) for n in nums):
        return {"ok": False, "message": "Numbers only after the id, please."}
    key = prefix.replace("-", "")
    # UUID v7 ids start with a timestamp, so the random tail (last 8 hex) is the unambiguous short id.
    pubs = [
        p
        for p in (
            await session.execute(select(Publication).order_by(desc(Publication.published_at)).limit(200))
        ).scalars()
        if len(key) >= 6 and (p.id.hex.endswith(key) or (p.id.hex.startswith(key) and len(key) >= 12))
    ]
    if len(pubs) != 1:
        return {"ok": False, "message": f"{'No' if not pubs else 'Several'} posts match id {prefix}."}
    pub = pubs[0]
    have = set(
        (await session.execute(select(Metric.horizon).where(Metric.publication_id == pub.id))).scalars()
    )
    horizon = "48h" if "48h" not in have else ("7d" if "7d" not in have else "custom")
    m = await record_metrics(
        session, pub, dict(zip(FIELDS, (int(n) for n in nums), strict=False)), horizon, "manual"
    )
    return {
        "ok": True,
        "metric_id": str(m.id),
        "horizon": horizon,
        "message": f"Saved {horizon} metrics for your {pub.platform} post ({m.impressions} impressions).",
    }


# ---------------- CSV import (LinkedIn / X analytics exports) ----------------
HEADER_MAP = {
    "impressions": ("impressions", "impression", "views"),
    "reactions": ("reactions", "likes", "like", "engagements reactions"),
    "comments": ("comments", "replies", "reply"),
    "reposts": ("reposts", "shares", "retweets", "repost"),
    "saves": ("saves", "bookmarks", "bookmark"),
    "profile_views": ("profile views", "profile visits", "user profile clicks"),
    "followers_gained": ("followers gained", "follows", "new followers"),
    "url": ("post url", "url", "tweet permalink", "permalink", "post link"),
    "date": ("date", "created date", "time", "post publish date", "created at"),
}


def _col(headers: Sequence[str], key: str) -> str | None:
    norm = {h.strip().lower(): h for h in headers}
    for cand in HEADER_MAP[key]:
        if cand in norm:
            return norm[cand]
    return None


def _num(v: str | None) -> int:
    if not v:
        return 0
    v = v.replace(",", "").strip()
    try:
        return int(float(v))
    except ValueError:
        return 0


async def import_csv(session: AsyncSession, data: str, platform: str) -> dict[str, int]:
    rdr = csv.DictReader(io.StringIO(data.lstrip("﻿")))
    headers = rdr.fieldnames or []
    ucol, icol = _col(headers, "url"), _col(headers, "impressions")
    if not ucol or not icol:
        raise ValueError(f"CSV needs a post URL and an impressions column (found: {headers})")
    pubs = {
        p.url.split("?")[0].rstrip("/"): p for p in (await session.execute(select(Publication))).scalars()
    }
    matched = created = 0
    for row in rdr:
        url = (row.get(ucol) or "").split("?")[0].rstrip("/")
        if not url:
            continue
        vals = {k: _num(row.get(c)) for k in FIELDS if (c := _col(headers, k))}
        pub = pubs.get(url)
        if pub is None:  # posts made outside SIGNAL still count (baseline / history)
            dcol = _col(headers, "date")
            try:
                when = datetime.fromisoformat((row.get(dcol) or "").strip()) if dcol else datetime.now(UTC)
            except ValueError:
                when = datetime.now(UTC)
            pub = Publication(
                platform=platform,
                url=url,
                published_at=when if when.tzinfo else when.replace(tzinfo=UTC),
                text="",
                variables={"imported": True},
            )
            session.add(pub)
            await session.flush()
            pubs[url] = pub
            created += 1
        else:
            matched += 1
        await record_metrics(session, pub, vals, "custom", "csv")
    return {"matched": matched, "created": created}


# ---------------- baseline & summary ----------------
async def latest_metric(session: AsyncSession, pub_id: uuid.UUID) -> Metric | None:
    rows = list(
        (
            await session.execute(
                select(Metric).where(Metric.publication_id == pub_id).order_by(desc(Metric.captured_at))
            )
        ).scalars()
    )
    for h in ("7d", "48h", "custom"):  # prefer the 7-day number when present
        for m in rows:
            if m.horizon == h:
                return m
    return None


async def baseline(session: AsyncSession, platform: str) -> dict[str, float] | None:
    pubs = list(
        (
            await session.execute(
                select(Publication)
                .where(Publication.is_baseline.is_(True), Publication.platform == platform)
                .order_by(desc(Publication.published_at))
                .limit(10)
            )
        ).scalars()
    )
    ms = [m for p in pubs if (m := await latest_metric(session, p.id))]
    if not ms:
        return None
    return {
        "impressions": statistics.median(m.impressions for m in ms),
        "engagement": statistics.median(engagement(m) for m in ms),
        "posts": len(ms),
    }


async def add_baseline_post(
    session: AsyncSession,
    platform: str,
    url: str,
    published_at: datetime,
    values: dict[str, int],
    text: str = "",
) -> Publication:
    p = Publication(
        platform=platform,
        url=url,
        published_at=published_at,
        text=text,
        is_baseline=True,
        variables={"baseline": True},
    )
    session.add(p)
    await session.flush()
    await record_metrics(session, p, values, "7d", "manual", published_at + timedelta(days=7))
    return p


async def summary(session: AsyncSession, now: datetime, days: int = 90) -> dict[str, Any]:
    pubs = list(
        (
            await session.execute(
                select(Publication)
                .where(
                    Publication.is_baseline.is_(False), Publication.published_at >= now - timedelta(days=days)
                )
                .order_by(desc(Publication.published_at))
            )
        ).scalars()
    )
    rows: list[dict[str, Any]] = []
    for p in pubs:
        m = await latest_metric(session, p.id)
        if m is not None:
            rows.append(
                {
                    "publication_id": str(p.id),
                    "platform": p.platform,
                    "url": p.url,
                    "published_at": p.published_at.isoformat(),
                    "impressions": m.impressions,
                    "engagement": engagement(m),
                    "variables": {k: v for k, v in (p.variables or {}).items() if not k.startswith("_")},
                }
            )
    by_platform: dict[str, Any] = {}
    for plat in sorted({r["platform"] for r in rows} | {"linkedin", "x"}):
        mine = [r for r in rows if r["platform"] == plat]
        base = await baseline(session, plat)
        med_imp = statistics.median(r["impressions"] for r in mine) if mine else None
        med_eng = statistics.median(r["engagement"] for r in mine) if mine else None
        by_platform[plat] = {
            "posts": len(mine),
            "median_impressions": med_imp,
            "median_engagement": med_eng,
            "baseline": base,
            "vs_baseline_impressions": round(med_imp / base["impressions"], 2)
            if base and med_imp and base["impressions"]
            else None,
            "trend": [
                {
                    "date": r["published_at"][:10],
                    "impressions": r["impressions"],
                    "engagement": r["engagement"],
                }
                for r in sorted(mine, key=lambda r: r["published_at"])
            ],
        }
    breakdowns: dict[str, dict[str, Any]] = {}
    for var in ("hook_type", "length_bucket", "format", "time_slot", "voice_version"):
        groups: dict[str, list[float]] = {}
        for r in rows:
            v = r["variables"].get(var)
            if v is not None:
                groups.setdefault(str(v), []).append(r["engagement"])
        breakdowns[var] = {
            k: {"n": len(v), "median_engagement": statistics.median(v), "caution": len(v) < MIN_SAMPLE}
            for k, v in groups.items()
        }
    top = sorted(rows, key=lambda r: -r["engagement"])[:5]
    return {
        "by_platform": by_platform,
        "breakdowns": breakdowns,
        "top_posts": top,
        "posts_measured": len(rows),
    }


async def experiment_result(session: AsyncSession, exp: Experiment) -> dict[str, Any]:
    pubs = list(
        (
            await session.execute(
                select(Publication).where(
                    Publication.published_at >= datetime.combine(exp.start, datetime.min.time(), UTC)
                )
            )
        ).scalars()
    )
    if exp.end:
        pubs = [p for p in pubs if p.published_at.date() <= exp.end]
    groups: dict[str, list[float]] = {}
    for p in pubs:
        v = (p.variables or {}).get(exp.variable)
        m = await latest_metric(session, p.id)
        if v is not None and m is not None:
            groups.setdefault(str(v), []).append(engagement(m))
    res = {k: {"n": len(v), "median_engagement": statistics.median(v)} for k, v in groups.items()}
    small = any(x["n"] < MIN_SAMPLE for x in res.values()) or len(res) < 2
    winner = None if small else max(res, key=lambda k: res[k]["median_engagement"])
    return {
        "variants": res,
        "winner": winner,
        "note": "Too few posts per variant to say anything yet."
        if small
        else "Directional only: small samples, one variable at a time.",
    }


# ---------------- monthly learnings (P16) ----------------
async def propose_learnings(
    session: AsyncSession, now: datetime, run_id: uuid.UUID | None = None
) -> dict[str, Any]:
    s = await summary(session, now, days=60)
    r = await llm.call(
        "metrics_learnings",
        {"summary": {k: v for k, v in s.items() if k != "top_posts"}, "top": s["top_posts"]},
        session=session,
        run_id=run_id,
        user_initiated=run_id is None,
    )
    proposal = {
        "id": uuid.uuid4().hex[:12],
        "created_at": now.isoformat(),
        "status": "proposed",
        **r.output.model_dump(),
        "prompt_version": r.prompt_version,
        "model": r.model,
    }
    props = list(await get_setting(session, "learning_proposals", []) or [])
    await set_setting(session, "learning_proposals", [proposal, *props][:24])
    return proposal


async def accept_learnings(session: AsyncSession, proposal_id: str) -> dict[str, Any]:
    from signal_core.studio.voice import active_voice, new_voice_version

    props = list(await get_setting(session, "learning_proposals", []) or [])
    prop = next((p for p in props if p["id"] == proposal_id), None)
    if prop is None:
        raise LookupError("proposal not found")
    if prop["status"] != "proposed":
        raise ValueError("proposal already decided")
    cur = await active_voice(session)
    rules = dict(prop.get("voice_rule_changes") or {})
    banned = list(cur.banned_phrases if cur else [])
    for ph in prop.get("add_banned_phrases") or []:
        if ph not in banned:
            banned.append(ph)
    v = await new_voice_version(
        session,
        rules=rules,
        banned_phrases=banned,
        note=f"monthly learnings {proposal_id}: " + "; ".join(prop.get("findings", [])[:2])[:200],
    )
    if prop.get("best_times"):
        await set_setting(session, "best_times", prop["best_times"])
    prop["status"], prop["voice_version"] = "accepted", v.version
    await set_setting(session, "learning_proposals", props)
    return {"voice_version": v.version, "proposal": prop}
