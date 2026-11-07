"""STUDIO visual & long-form formats (M5): carousels (Instagram, LinkedIn document), reel script packages,
Hashnode articles, quote/stat cards. Rendering via `signal_core.render`.

Validators: carousel slide count/words per slide, reel hook ≤ hook_seconds_max and contiguous timestamps summing to
30–60 s, article Markdown with YAML front-matter and balanced code fences, references only from source URLs.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import Asset, Draft, DraftVersion, Item
from signal_core.llm import router as llm
from signal_core.render.renderer import assets_dir, render
from signal_core.services.settings_store import flag, get_setting
from signal_core.studio import service as base
from signal_core.studio.aitell import scan
from signal_core.studio.voice import active_voice
from signal_core.truth import disallowed_urls

FORMATS = {
    "instagram_carousel": "carousel",
    "linkedin_carousel": "doc_carousel",
    "instagram_reel": "reel",
    "hashnode": "article",
}
LABELS = {"instagram_carousel": "Instagram carousel", "linkedin_carousel": "LinkedIn document carousel (PDF)"}
RUBRICS = {
    "carousel": [
        {"name": "Slide-1 hook", "points": 3, "full": "slide 1 alone stops the scroll"},
        {"name": "One idea per slide", "points": 2, "full": "no slide carries two ideas"},
        {"name": "Visual readability", "points": 2, "full": "big type, ≤ 30 words per slide"},
        {"name": "Payoff slide", "points": 2, "full": "the last slides deliver the promise"},
        {"name": "CTA", "points": 1, "full": "clear ask at the end"},
    ],
    "reel": [
        {"name": "First 2 seconds", "points": 3, "full": "hook lands in ≤ 2 s"},
        {"name": "Pacing", "points": 2, "full": "beats move every few seconds"},
        {"name": "On-screen text", "points": 2, "full": "short, readable, adds to voice-over"},
        {"name": "Retention beats", "points": 2, "full": "a reason to keep watching each beat"},
        {"name": "CTA", "points": 1, "full": "clear ask"},
    ],
    "article": [
        {"name": "Structure", "points": 2, "full": "TL;DR, sections, takeaway"},
        {"name": "Technical accuracy", "points": 3, "full": "every claim sourced, no hand-waving"},
        {"name": "Code correctness", "points": 2, "full": "code is minimal and correct"},
        {"name": "SEO title", "points": 1, "full": "specific, ≤ 70 characters"},
        {"name": "Takeaway", "points": 2, "full": "one actionable lesson"},
    ],
}


def _spec(platform: str) -> dict[str, Any]:
    vp = get_config().voice.platforms
    return dict(vp.get("instagram_carousel" if platform.endswith("carousel") else platform, {}))


def validate_carousel(slides: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    lo, hi = spec.get("slides", [6, 10])
    if not lo <= len(slides) <= hi:
        issues.append(
            {"type": "slides", "message": f"{len(slides)} slides (target {lo}–{hi})", "severity": "error"}
        )
    wmax = int(spec.get("words_per_slide_max", 30))
    for i, s in enumerate(slides, 1):
        n = len((s.get("title", "") + " " + s.get("body", "")).split())
        if n > wmax:
            issues.append(
                {"type": "words", "message": f"slide {i} has {n} words (max {wmax})", "severity": "error"}
            )
        if not s.get("alt"):
            issues.append({"type": "alt", "message": f"slide {i} has no alt text", "severity": "warn"})
    return issues


def validate_reel(script: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    lo, hi = spec.get("seconds", [30, 60])
    hook_max = float(spec.get("hook_seconds_max", 2))
    hook, beats = script["hook"], script["beats"]
    if hook["t_start"] != 0 or hook["t_end"] > hook_max:
        issues.append(
            {
                "type": "hook",
                "message": f"hook must run 0–{hook_max}s (got {hook['t_start']}–{hook['t_end']})",
                "severity": "error",
            }
        )
    prev = hook["t_end"]
    for i, b in enumerate(beats, 1):
        if abs(b["t_start"] - prev) > 0.05:
            issues.append(
                {
                    "type": "timestamps",
                    "message": f"beat {i} starts at {b['t_start']}s, expected {prev}s",
                    "severity": "error",
                }
            )
        if b["t_end"] <= b["t_start"]:
            issues.append(
                {"type": "timestamps", "message": f"beat {i} ends before it starts", "severity": "error"}
            )
        prev = b["t_end"]
    if not lo <= prev <= hi:
        issues.append(
            {"type": "duration", "message": f"total {prev}s (target {lo}–{hi}s)", "severity": "error"}
        )
    return issues


def article_markdown(a: dict[str, Any], canonical_url: str | None = None) -> str:
    fm = {
        "title": a["seo_title"],
        "subtitle": a.get("subtitle", ""),
        "tags": a.get("tags", []),
        "canonical_url": canonical_url or "",
        "cover_title": a.get("cover_title", ""),
        "date": datetime.now(UTC).date().isoformat(),
    }
    refs = "\n".join(f"- [{r['title']}]({r['url']})" for r in a.get("references", []))
    body = f"> **TL;DR** {a['tldr']}\n\n{a['body_md'].strip()}\n"
    if refs:
        body += f"\n## References\n\n{refs}\n"
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + body


def validate_markdown(md: str, allowed_urls: set[str], words: list[int]) -> list[dict[str, Any]]:
    issues = []
    if not md.startswith("---\n") or md.count("\n---\n") < 1:
        issues.append({"type": "front_matter", "message": "missing YAML front-matter", "severity": "error"})
    else:
        try:
            fm = yaml.safe_load(md.split("---\n", 2)[1])
            if not isinstance(fm, dict) or not fm.get("title"):
                raise ValueError("no title")
        except Exception as e:
            issues.append(
                {"type": "front_matter", "message": f"invalid front-matter: {e}", "severity": "error"}
            )
    fences = re.findall(r"^```", md, re.M)
    if len(fences) % 2:
        issues.append({"type": "code_fence", "message": "unbalanced code fences", "severity": "error"})
    opening = re.findall(r"^```(\S*)\s*$", md, re.M)[::2]
    if any(not lang for lang in opening):
        issues.append(
            {"type": "code_fence", "message": "code block without a language tag", "severity": "warn"}
        )
    bad = disallowed_urls(md, allowed_urls)
    if bad:
        issues.append({"type": "url", "message": f"URLs not in sources: {bad[:3]}", "severity": "error"})
    n = len(md.split())
    if words and not words[0] <= n <= words[1] + 300:
        issues.append(
            {"type": "length", "message": f"{n} words (target {words[0]}–{words[1]})", "severity": "warn"}
        )
    return issues


async def generate_format(session: AsyncSession, d: Draft, repurpose: str | None = None) -> DraftVersion:
    cfg = get_config()
    voice = await active_voice(session)
    idea, ctx, raw = await base._context(session, d)
    rules = dict(voice.rules if voice else {})
    banned = list(voice.banned_phrases if voice else cfg.voice.banned_phrases)
    sources = ctx.sources
    if sources:
        urls = {
            str(i.id): i.canonical_url
            for i in (
                await session.execute(
                    select(Item).where(
                        Item.id.in_([uuid.UUID(s["id"]) for s in sources if not s["id"].startswith("log:")])
                    )
                )
            ).scalars()
        }
        sources = [{**s, "url": urls.get(s["id"], "")} for s in sources]
    spec = _spec(d.platform)
    common = {
        "owner": cfg.profile.owner.name,
        "role": cfg.profile.owner.role,
        "banned": banned,
        "angle": {"angle_type": idea.angle_type, "thesis": idea.thesis},
        "sources": sources,
        "raw": [{"id": str(r.id), "text": r.text} for r in raw],
        "repurpose": repurpose,
    }
    fmt = FORMATS[d.platform]
    n = (
        await session.execute(
            select(func.coalesce(func.max(DraftVersion.version), 0)).where(DraftVersion.draft_id == d.id)
        )
    ).scalar_one()
    dv = DraftVersion(
        draft_id=d.id, version=n + 1, label="A", voice_version=voice.version if voice else 1, author="ai"
    )
    issues: list[dict[str, Any]] = []
    if fmt in ("carousel", "doc_carousel"):
        w = await llm.call(
            "carousel_writer",
            {
                **common,
                "platform_label": LABELS[d.platform],
                "slides_min": spec.get("slides", [6, 10])[0],
                "slides_max": spec.get("slides", [6, 10])[1],
                "words_max": spec.get("words_per_slide_max", 30),
                "hashtags": spec.get("hashtags") if d.platform.startswith("instagram") else None,
            },
            session=session,
            user_initiated=True,
        )
        o = w.output
        dv.slides = {"template": o.template, "items": [s.model_dump(exclude_none=True) for s in o.slides]}
        dv.body = o.caption
        dv.claims = [c.model_dump() for c in o.claims]
        issues = validate_carousel(dv.slides["items"], spec)
        draft_text = (
            "\n\n".join(f"{s['title']}. {s.get('body', '')}" for s in dv.slides["items"]) + "\n\n" + o.caption
        )
    elif fmt == "reel":
        w = await llm.call(
            "reel_writer",
            {**common, "seconds": spec.get("seconds", [30, 60]), "hook_max": spec.get("hook_seconds_max", 2)},
            session=session,
            user_initiated=True,
        )
        o = w.output
        dv.script = o.model_dump(exclude={"claims"})
        dv.body = o.caption
        dv.claims = [c.model_dump() for c in o.claims]
        issues = validate_reel(dv.script, spec)
        draft_text = o.hook.voiceover + "\n" + "\n".join(b.voiceover for b in o.beats)
    else:
        w = await llm.call(
            "article_writer",
            {**common, "words": spec.get("words", [1200, 2500])},
            session=session,
            user_initiated=True,
        )
        o = w.output
        allowed = {s["url"] for s in sources if s.get("url")}
        refs = [r.model_dump() for r in o.references if r.url in allowed]  # never keep invented references
        art = {**o.model_dump(exclude={"claims"}), "references": refs}
        dv.script = {"article": art}
        dv.body = article_markdown(art)
        dv.claims = [c.model_dump() for c in o.claims]
        issues = validate_markdown(dv.body, allowed, spec.get("words", [1200, 2500]))
        draft_text = dv.body
    dv.prompt_version, dv.model = w.prompt_version, w.model
    session.add(dv)
    await session.flush()
    await base.run_checks(session, d, dv, sources, raw, rules, banned, [], grade=False)
    # Citations must cover the slides / beats / article, not only the caption.
    dv.factcheck = {
        **(dv.factcheck or {}),
        "uncited_sentences": base.uncited_factual_sentences(draft_text, dv.claims or []),
    }
    # Format validators + text scan (banned phrases/chars, hashtag limits; length rules are format-specific).
    sc = scan(
        draft_text,
        rules,
        banned,
        d.platform,
        spec if d.platform.startswith("instagram") else {},
        fmt="format",
    )
    dv.aitell = {**sc.as_dict(), "issues": [*(i for i in sc.as_dict()["issues"]), *issues]}
    g = await llm.call(
        "grader",
        {
            "platform": d.platform,
            "rubric": RUBRICS["carousel" if "carousel" in fmt else fmt],
            "references": [],
            "draft": draft_text[:6000],
        },
        session=session,
        user_initiated=True,
    )
    dv.grade = g.output.model_dump()
    d.current_version_id = dv.id
    await session.flush()
    return dv


async def render_draft(session: AsyncSession, d: Draft) -> list[Asset]:
    dv = await base.current_version(session, d)
    brand = await get_setting(session, "brand_kit")
    out = assets_dir(str(d.id)) / f"v{dv.version}"
    assets: list[Asset] = []
    if dv.slides:
        res = await render("carousel", dv.slides["template"], dv.slides["items"], brand, out)
        for p, alt in zip(res.pngs, res.alt, strict=True):
            assets.append(
                Asset(
                    draft_id=d.id,
                    kind="png",
                    path=str(p),
                    meta={"alt": alt, "w": res.size[0], "h": res.size[1]},
                )
            )
        if res.pdf:
            assets.append(
                Asset(
                    draft_id=d.id,
                    kind="pdf",
                    path=str(res.pdf),
                    meta={"pages": len(res.pngs), "contrast": res.contrast, "min_font_px": res.min_font_px},
                )
            )
    elif dv.script and "hook" in dv.script:
        res = await render(
            "reel_cover",
            "reel-cover",
            [{"title": dv.script.get("cover_text") or "", "body": ""}],
            brand,
            out,
            pdf=False,
        )
        assets.append(Asset(draft_id=d.id, kind="png", path=str(res.pngs[0]), meta={"role": "reel_cover"}))
    elif dv.script and "article" in dv.script:
        art = dv.script["article"]
        res = await render(
            "article_cover",
            "article-cover",
            [{"title": art.get("cover_title") or art["seo_title"], "body": art.get("subtitle", "")}],
            brand,
            out,
            pdf=False,
        )
        md = out / "article.md"
        md.write_text(dv.body, encoding="utf-8")
        assets += [
            Asset(draft_id=d.id, kind="png", path=str(res.pngs[0]), meta={"role": "cover"}),
            Asset(draft_id=d.id, kind="md", path=str(md), meta={"words": len(dv.body.split())}),
        ]
    for a in assets:
        session.add(a)
    await session.flush()
    return assets


async def render_card(
    session: AsyncSession, kind: str, title: str, body: str, source: str | None, key: str
) -> Asset:
    brand = await get_setting(session, "brand_kit")
    res = await render(
        kind,
        kind.replace("_", "-"),
        [{"title": title, "body": body, "source": source}],
        brand,
        assets_dir("cards") / key,
        pdf=False,
    )
    a = Asset(kind="png", path=str(res.pngs[0]), meta={"kind": kind, "alt": res.alt[0]})
    session.add(a)
    await session.flush()
    return a


# ---------------- Hashnode publishing (flagged, explicit per-post approval) ----------------
PUBLISH_MUTATION = (
    "mutation Publish($input: PublishPostInput!) { publishPost(input: $input) { post { id slug url } } }"
)


class PublishError(RuntimeError):
    pass


class HashnodeClient:
    """Hashnode GraphQL `publishPost` (schema verified 2026-11-07 from Hashnode's generated starter-kit schema;
    auth header is the raw PAT, ADR-019). GraphQL errors can arrive with HTTP 200 — always checked."""

    def __init__(self, token: str, endpoint: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.token, self.endpoint, self.transport = token, endpoint, transport

    async def publish(
        self,
        publication_id: str,
        md: str,
        title: str,
        subtitle: str,
        tags: list[str],
        canonical: str | None = None,
    ) -> dict[str, Any]:
        body_md = (
            md.split("---\n", 2)[2] if md.startswith("---\n") else md
        )  # Hashnode takes metadata separately
        inp: dict[str, Any] = {
            "title": title,
            "contentMarkdown": body_md.strip(),
            "publicationId": publication_id,
            "tags": [{"name": t, "slug": re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")} for t in tags[:5]],
        }
        if subtitle:
            inp["subtitle"] = subtitle
        if canonical:
            inp["originalArticleURL"] = canonical
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as c:
            r = await c.post(
                self.endpoint,
                json={"query": PUBLISH_MUTATION, "variables": {"input": inp}},
                headers={"authorization": self.token, "content-type": "application/json"},
            )
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or data.get("errors"):
            raise PublishError(f"Hashnode rejected the post: {data.get('errors') or r.text[:300]}")
        return dict(data["data"]["publishPost"]["post"])


async def publish_via_api(
    session: AsyncSession, d: Draft, confirm: bool, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """Never auto-posts: requires the feature flag, a token, a Ready draft and confirm=true for THIS post."""
    from signal_core.settings import get_settings

    if d.platform != "hashnode":
        raise PublishError(
            "API publishing is only implemented for Hashnode; other platforms use publish-assist"
        )
    if not await flag(session, "publish.hashnode_api"):
        raise PublishError(
            "Hashnode API publishing is disabled (Settings → Feature flags → publish.hashnode_api)"
        )
    s = get_settings()
    if not s.hashnode_token:
        raise PublishError("SIGNAL_HASHNODE_TOKEN is not set")
    pub_id = await get_setting(session, "hashnode_publication_id", "")
    if not pub_id:
        raise PublishError("set hashnode_publication_id in Settings")
    if d.status not in ("ready", "scheduled"):
        raise PublishError("draft must be approved (Ready) first")
    if not confirm:
        raise PublishError("explicit confirmation for this specific post is required")
    dv = await base.current_version(session, d)
    art = (dv.script or {}).get("article", {})
    client = HashnodeClient(s.hashnode_token, get_config().platforms.hashnode["graphql_endpoint"], transport)
    post = await client.publish(
        pub_id, dv.body, art.get("seo_title", ""), art.get("subtitle", ""), art.get("tags", [])
    )
    pub = await base.mark_published(session, d, post.get("url", ""), datetime.now(UTC))
    pub.variables = {
        **(pub.variables or {}),
        "published_via": "hashnode_api",
        "hashnode_post_id": post.get("id"),
    }
    await session.flush()
    return {"post": post, "publication_id": str(pub.id)}
