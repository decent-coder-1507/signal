"""Deterministic mock outputs per task (ADR-009).

Generators are pure functions of the inputs and only ever quote text that exists in the inputs, so mock mode
exercises the same truth validators (verbatim quote spans, resolvable citations) as live mode.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from signal_core.llm.mock import mock_generator

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_NUM = re.compile(r"\d")
_CAP = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:[- ][A-Z0-9][a-zA-Z0-9.]*)*)")
HYPE = re.compile(r"\b(revolutionary|game-?changing|groundbreaking|massive|stunning|incredible)\b", re.I)
WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
STOP_CAPS = {
    "The",
    "A",
    "An",
    "This",
    "Today",
    "We",
    "It",
    "Our",
    "In",
    "On",
    "For",
    "If",
    "I",
    "Abstract",
    "Release",
    "Notes",
    "Another",
    "Trending",
    "Daily",
    "From",
    "According",
    "Security",
    "Policy",
    "Chip",
    "Hardware",
    "Startup",
    "Indian",
    "Open-source",
    "Hiring",
    "Version",
    "Public",
    "Volume",
    "Vendors",
}


def sents(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def h(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


@mock_generator("ping")
def ping(inputs: dict[str, Any]) -> dict[str, Any]:
    return {"answer": f"pong: {inputs.get('message', '')}", "ok": True}


# ---------------- P1 ----------------
def _looks_proper(name: str) -> bool:
    """Proper-name shape: has a digit, an inner capital (CamelCase / 'AI'), or several capitalised words."""
    return bool(_NUM.search(name)) or any(c.isupper() for c in name[1:]) or len(name.split()) >= 2


def _entities(text: str) -> dict[str, list[str]]:
    caps = []
    for s in sents(text):
        for m in _CAP.finditer(s):
            name = m.group(1).strip().rstrip(".,;:")
            if name.split()[0] in STOP_CAPS or name in WEEKDAYS or len(name) < 3:
                continue
            at_start = m.start() == 0
            if at_start and not _looks_proper(name):
                continue  # "Researchers …" / "Sandbox …" at sentence start are ordinary words
            if not at_start and not _looks_proper(name) and name.lower() in s.lower()[: m.start()]:
                continue
            caps.append(name)
    seen: list[str] = []
    for c in caps:
        if c not in seen:
            seen.append(c)
    models = [c for c in seen if _NUM.search(c) and "-" in c]
    companies = [
        c for c in seen if c not in models and (c.endswith(("AI", "Labs", "Semi", "Board")) or " " in c)
    ]
    products = [c for c in seen if c not in models and c not in companies][:6]
    repos = re.findall(r"\b([a-z0-9-]+/[a-z0-9._-]+)\b", text)
    return {
        "companies": companies[:6],
        "people": [],
        "products": products,
        "models": models[:6],
        "repos": sorted(set(repos))[:4],
        "papers": [],
    }


ENRICH_TYPE = {
    "paper": "research",
    "release": "release",
    "repo": "launch",
    "launch": "launch",
    "post": "opinion",
    "newsletter": "other",
    "video": "tutorial",
    "podcast": "opinion",
}


def enrich_one(it: dict[str, Any], topics: list[str]) -> dict[str, Any]:
    text = it.get("text") or it.get("title", "")
    ss = sents(text)
    factual = [s for s in ss if (_NUM.search(s) or _CAP.search(s)) and len(s.split()) >= 5]
    facts = []
    for s in factual[:5]:
        span = s if len(s.split()) <= 40 else " ".join(s.split()[:40])
        facts.append({"fact": HYPE.sub("", s).strip(), "quote_span": span})
    first = HYPE.sub("", (factual or ss or [it.get("title", "")])[0]).strip()
    words = first.split()
    one = " ".join(words[:25])
    lower = (it.get("title", "") + " " + text).lower()
    tps = [t for t in topics if any(k in lower for k in t.replace("-", " ").split() if len(k) > 3)][:3]
    pre = (it.get("prefilter") or {}).get("best")
    if pre and pre in topics and pre not in tps:
        tps.insert(0, pre)
    ring = it.get("ring") or "core"
    adjacent_words = (
        "funding",
        "raised",
        "series",
        "chip",
        "accelerator",
        "guideline",
        "policy",
        "survey",
        "hiring",
    )
    tech = 0.85 if ring == "core" else (0.55 if any(w in lower for w in adjacent_words) else 0.4)
    if any(
        w in lower
        for w in ("developer", "engineer", "api", "inference", "agent", "model", "open-source", "code")
    ):
        tech = min(1.0, tech + 0.1)
    claims = [s for s in ss if re.search(r"\b(says|claims|report|reports|according)\b", s, re.I)][:3]
    return {
        "item_id": it["item_id"],
        "summary_1line": one,
        "summary_short": " ".join(HYPE.sub("", s) for s in ss[:4]),
        "key_facts": facts,
        "entities": _entities(text),
        "topics": tps,
        "ring": ring if ring in ("core", "adjacent", "wide") else "core",
        "content_type": ENRICH_TYPE.get(it.get("content_type", ""), "other"),
        "tech_relevance": round(tech, 2),
        "claims_needing_verification": claims,
        "is_primary_source": bool(it.get("tier") == 1),
        "language": "en",
    }


@mock_generator("enrich_items")
def enrich_items(inputs: dict[str, Any]) -> dict[str, Any]:
    return {"items": [enrich_one(it, inputs.get("topics", [])) for it in inputs["items"]]}


# ---------------- P2 ----------------
DURABLE_HINTS = (
    ("protocol", "fundamental"),
    ("guideline", "fundamental"),
    ("regulat", "fundamental"),
    ("price", "trend"),
    ("pricing", "trend"),
    ("open-weights", "trend"),
    ("open weights", "trend"),
    ("paper", "fundamental"),
    ("verifier", "fundamental"),
    ("injection", "fundamental"),
    ("release", "churn"),
    ("v2.", "churn"),
    ("trending", "churn"),
)


@mock_generator("story_insight")
def story_insight(inputs: dict[str, Any]) -> dict[str, Any]:
    items = inputs["items"]
    prof = inputs["profile"]
    lines: list[str] = []
    for it in items:
        for s in sents(it["text"]):
            if (_NUM.search(s) or _CAP.search(s)) and s not in " ".join(lines) and len(lines) < 4:
                lines.append(f"{s} [{it['item_id']}]")
    if not lines:
        lines = [f"{items[0]['title']}. [{items[0]['item_id']}]"]
    blob = " ".join(it["title"] + " " + it["text"] for it in items).lower()
    matched = [g for g in prof.get("goals", []) if any(w in blob for w in g.lower().split() if len(w) > 5)]
    stack = [t for t in prof.get("stack", []) if t.lower() in blob]
    if matched or stack or any(k in blob for k in ("agent", "model", "inference", "coding", "retrieval")):
        why = (
            f'Relevant to your goal "{(matched or prof.get("goals", ["your work"]))[0]}"'
            + (f" and your stack ({', '.join(stack)})" if stack else "")
            + ": it affects tools and techniques you use when shipping LLM features."
        )
    else:
        why = "Low personal relevance: useful background on the wider ecosystem, not a change to your daily work."
    self_reported = "self-reported" in blob or "says" in blob or "claims" in blob
    n_src = len({it["source"] for it in items})
    verdict = "mixed" if self_reported and n_src < 3 else ("too_early" if "draft" in blob else "substance")
    dur = next((d for k, d in DURABLE_HINTS if k in blob), "trend")
    first_id = items[0]["item_id"]
    actions = [
        {
            "type": "post",
            "label": "LinkedIn practitioner take on what this changes for teams shipping LLM apps",
            "platform": "linkedin",
            "angle": "practitioner",
        },
        {"type": "learn", "label": "Evals & testing of LLM apps", "skill": "Evals & testing of LLM apps"},
        {"type": "watch", "label": f"Follow-ups on: {items[0]['title'][:60]}"},
    ]
    if any(k in blob for k in ("open-source", "release", "protocol", "framework", "api")):
        actions.insert(
            1, {"type": "try", "label": "Spend 45 minutes trying it on one real task from your backlog"}
        )
    labels = []
    if n_src == 1:
        labels.append("single source")
    if self_reported:
        labels.append("company claim, not independently verified")
    if "benchmark" in blob or "swe-bench" in blob:
        labels.append("benchmark self-reported")
    words = sum(len(it["text"].split()) for it in items[:1])
    return {
        "what_happened": " ".join(lines),
        "why_it_matters_to_you": why,
        "what_changes": f"Teams can evaluate this against their current setup; details are in the sources [{first_id}].",
        "hype_verdict": verdict,
        "hype_reasons": (
            ["Figures come from the company and are not independently confirmed."]
            if self_reported
            else [f"Reported by {n_src} independent sources."]
        ),
        "durability": dur,
        "durability_reason": {
            "fundamental": "Changes a standard, capability or cost structure.",
            "trend": "Part of an ongoing shift; specifics will change.",
            "churn": "Incremental version update.",
        }[dur],
        "moat_note": "The capability itself commoditises quickly; evaluation discipline and domain data stay defensible.",
        "open_questions": [
            "Do independent evaluations confirm the claims?",
            "What does it cost in production?",
        ],
        "actions": actions,
        "confidence": round(min(0.9, 0.45 + 0.15 * n_src), 2),
        "confidence_reason": f"{n_src} source(s); {'includes' if any(it.get('primary') for it in items) else 'no'} primary source.",
        "reading_time": max(1, words // 200),
        "uncertainty_labels": labels,
    }


# ---------------- P3 / title / tiebreak ----------------
@mock_generator("relevance_judge")
def relevance_judge(inputs: dict[str, Any]) -> dict[str, Any]:
    prof, story = inputs["profile"], inputs["story"]
    blob = (story["title"] + " " + " ".join(story["summaries"])).lower()
    topics = [
        t for t in prof.get("topics", []) if any(w in blob for w in t.replace("-", " ").split() if len(w) > 3)
    ]
    goals = [g for g in prof.get("goals", []) if any(w in blob for w in g.lower().split() if len(w) > 6)]
    core_kw = (
        "agent",
        "model",
        "inference",
        "coding",
        "retrieval",
        "protocol",
        "evaluation",
        "prompt injection",
    )
    rel = (
        0.35
        + 0.15 * min(len(topics), 2)
        + 0.1 * min(len(goals), 1)
        + (0.15 if any(k in blob for k in core_kw) else 0)
    )
    impact = (
        0.7
        if any(
            k in blob
            for k in ("all developers", "price", "protocol", "injection", "open-weights", "open weights")
        )
        else 0.5
    )
    dur = next((d for k, d in DURABLE_HINTS if k in blob), "trend")
    return {
        "relevance": round(min(rel, 0.95), 2),
        "reason": "Matches: " + (", ".join(topics) or "few profile topics"),
        "matched_goals": goals,
        "matched_topics": topics,
        "impact": impact,
        "durability": dur,
        "content_potential": 0.7 if rel > 0.6 else 0.4,
        "build_potential": 0.7
        if any(k in blob for k in ("open-source", "framework", "api", "protocol", "price"))
        else 0.3,
        "learn_potential": 0.7 if dur == "fundamental" else 0.4,
    }


@mock_generator("story_title")
def story_title(inputs: dict[str, Any]) -> dict[str, Any]:
    titles = sorted(inputs["titles"], key=lambda t: (-sum(c.isdigit() for c in t), len(t)))
    t = titles[0].split(" | ")[0]
    return {"title": " ".join(t.split()[:16])}


@mock_generator("cluster_tiebreak")
def cluster_tiebreak(inputs: dict[str, Any]) -> dict[str, Any]:
    a = set(re.findall(r"[A-Za-z0-9-]{4,}", inputs["a"]["title"].lower()))
    b = set(re.findall(r"[A-Za-z0-9-]{4,}", inputs["b"]["title"].lower()))
    j = len(a & b) / max(1, len(a | b))
    return {"same_event": j >= 0.35, "reason": f"title overlap {j:.2f}"}


@mock_generator("brief_topline")
def brief_topline(inputs: dict[str, Any]) -> dict[str, Any]:
    titles = inputs.get("titles") or []
    if not titles:
        return {"topline": "Quiet day: nothing important cleared the bar."}
    lead = titles[0].rstrip(".")
    more = len(titles) - 1
    return {
        "topline": f"{lead}"
        + (f", plus {more} more {'story' if more == 1 else 'stories'} worth your time." if more else ".")
    }


@mock_generator("watch_check")
def watch_check(inputs: dict[str, Any]) -> dict[str, Any]:
    q = {w for w in re.findall(r"[a-z0-9-]{4,}", inputs["query"].lower())} - {
        "tell",
        "when",
        "about",
        "with",
        "that",
        "updates",
        "any",
        "news",
    }
    blob = (inputs["story"]["title"] + " " + " ".join(inputs["story"]["summaries"])).lower()
    hits = sorted(w for w in q if w in blob)
    ok = len(hits) >= max(1, min(2, len(q) // 2))
    return {
        "triggered": ok,
        "explanation": ("Matches: " + ", ".join(hits)) if ok else "No match on the watch condition.",
    }


# ---------------- STUDIO ----------------
ANGLE_ORDER = ["practitioner", "contrarian", "how_to", "personal_story", "india_lens"]


@mock_generator("angles")
def angles(inputs: dict[str, Any]) -> dict[str, Any]:
    title = inputs.get("seed_title") or "this"
    has_raw = bool(inputs.get("raw"))
    out = []
    for t in ANGLE_ORDER[:4]:
        thesis = {
            "practitioner": f"What {title[:70]} actually changes for teams shipping LLM features",
            "contrarian": f"The headline number in {title[:60]} is not the part that matters",
            "how_to": f"A 10-minute way to test {title[:60]} on your own backlog",
            "personal_story": f"Where {title[:60]} meets what I see at work",
            "india_lens": f"What {title[:60]} means for engineers in India",
        }[t]
        needs = (
            []
            if t != "personal_story" or has_raw
            else [
                {
                    "question": "Have you used something like this at VANCO? One line on what happened.",
                    "why": "Personal angle needs a real detail.",
                }
            ]
        )
        out.append(
            {
                "angle_type": t,
                "thesis": thesis,
                "credibility": "Builds production LLM systems daily; stack overlaps the topic.",
                "needs_input": needs,
                "platforms": ["linkedin", "x"] if t != "how_to" else ["x_thread", "linkedin"],
                "risk": "low",
            }
        )
    return {"angles": out}


def _compress(sent: str) -> str:
    """Short line around the first number (names/numbers verbatim, never a 15+ word copy of the source)."""
    toks = sent.rstrip(".").split()
    nums = [k for k, t in enumerate(toks) if _NUM.search(t)]
    # Anchor on the most informative number ("212 lines" beats "Day 1").
    i = max(nums, key=lambda k: sum(c.isdigit() for c in toks[k])) if nums else None
    window = toks[max(0, i - 4) : i + 5] if i is not None else toks[:9]
    line = " ".join(window).strip(",;:")
    line = re.sub(r",\s*\w+$", "", line)
    return (line[:1].upper() + line[1:]).rstrip(",") + "."


def _fact_lines(sources: list[dict[str, Any]], n: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in sources:
        for sent in sents(s.get("text", "")):
            if (_NUM.search(sent) or _CAP.search(sent[1:])) and not HYPE.search(sent):
                line = _compress(sent)
                if line not in [x for x, _ in out] and len(line.split()) >= 4:
                    out.append((line, s["id"]))
            if len(out) >= n:
                return out
    return out


@mock_generator("writer")
def writer(inputs: dict[str, Any]) -> dict[str, Any]:
    platform = inputs.get("platform", "linkedin")
    sources = inputs.get("sources", [])
    raw = inputs.get("raw", [])
    emoji = (inputs.get("voice", {}).get("rules", {}).get("emoji", {}).get("set") or ["🚀"])[0]
    facts = _fact_lines(sources, 4)
    claims = [{"sentence": f, "source_ids": [sid]} for f, sid in facts]
    personal = [(r["text"].strip().rstrip("."), r["id"]) for r in raw[:1]]
    for p, rid in personal:
        claims.append({"sentence": p + ".", "source_ids": [f"r:{rid}"]})
    thesis = inputs.get("angle", {}).get("thesis", "")
    if platform in ("x", "x_thread"):
        first = facts[0][0] if facts else thesis
        if platform == "x":
            body = f"{first}\n\nThe interesting part is what it changes for people shipping LLM features.\n\nWhat would you test first?"
            if len(body) > 280:
                body = f"{first[:200]}\n\nWhat would you test first?"
            return {"versions": [{"label": "A", "body": body}], "claims": claims[:1]}
        posts = [f"{thesis[:200]} 🧵"]
        posts += [f[:270] for f, _ in facts[:3]]
        if personal:
            posts.append(personal[0][0][:270] + ".")
        posts.append("What would you try first? Links to the sources in the reply.")
        while len(posts) < 4:
            posts.insert(-1, "The part worth watching is how this holds up outside the benchmark.")
        return {"versions": [{"label": "A", "body": "\n\n".join(posts), "thread": posts}], "claims": claims}
    hook = (personal[0][0] + ".") if personal else (facts[0][0] if facts else thesis)
    lines = [hook, ""]
    for f, _ in facts[1 if not personal else 0 : 4]:
        lines += [f, ""]
    lines += [
        "Benchmarks are a starting point, not the answer.",
        "",
        "I would test it on one real task before changing anything.",
        "",
        f"What would you check first? {emoji}",
    ]
    body_a = "\n".join(lines)
    short = [facts[0][0] if facts else thesis, "", f"Would you switch your stack for this? {emoji}"]
    return {
        "versions": [
            {"label": "A", "body": body_a, "first_comment": "Sources in the links below."},
            {"label": "B", "body": "\n".join(short)},
        ],
        "claims": claims,
    }


@mock_generator("grader")
def grader(inputs: dict[str, Any]) -> dict[str, Any]:
    draft = inputs.get("draft", "")
    low = draft.lower()
    score = {
        "Hook": 1.6,
        "Rhythm": 1.7,
        "Specificity": 1.6,
        "Voice match": 1.6,
        "Ending": 1.0,
        "Restraint": 0.9,
    }
    ai_phrases = [
        p
        for p in (
            "here's the thing",
            "game-changer",
            "let that sink in",
            "delve",
            "unlock",
            "in today's fast-paced world",
        )
        if p in low
    ]
    if ai_phrases:
        score["Voice match"] = 0.5
    if "—" in draft:
        score["Rhythm"] -= 0.7
    if not draft.rstrip().endswith(("?", "?" + draft.rstrip()[-1:])) and "?" not in draft[-40:]:
        score["Ending"] = 0.3
    if not _NUM.search(draft):
        score["Specificity"] = 1.0
    total = round(sum(score.values()), 1)
    edits = [
        "Open with the most concrete number or quote",
        "Cut the abstract lines; keep one plain lesson",
        "End on a specific question your peers can answer",
    ]
    return {
        "scores": {k: {"points": round(v, 1), "why": ""} for k, v in score.items()},
        "total": min(total, 10),
        "ai_phrases": ai_phrases,
        "top_edits": edits[:3],
        "verdict": "would post" if total >= 8 else "would not post yet",
    }


@mock_generator("factcheck")
def factcheck(inputs: dict[str, Any]) -> dict[str, Any]:
    out = []
    for c in inputs.get("claims", []):
        src = " ".join(s.get("text", "") for s in c.get("sources", []))
        sent = c["sentence"]
        nums = [t.strip(".,;:()\"'") for t in sent.split() if _NUM.search(t)]

        def found(tok: str, src: str = src) -> bool:  # whole-token match: "$1" must not match "$15"
            return re.search(r"(?<![\w$])" + re.escape(tok) + r"(?![\w])", src) is not None

        if not src.strip():
            v, ev = "unsupported", ""
        elif sent.strip().rstrip(".") in src or (nums and all(found(n) for n in nums)):
            v, ev = "supported", next((s for s in sents(src) if any(found(n) for n in nums)), sent)
        elif not nums and sum(w in src.lower() for w in sent.lower().split()) >= len(sent.split()) * 0.6:
            v, ev = "supported", sent
        else:
            v, ev = "unsupported", ""
        out.append(
            {
                "sentence": sent,
                "verdict": v,
                "evidence_span": ev,
                "fix_suggestion": ""
                if v == "supported"
                else "Remove or rewrite using only the cited source.",
            }
        )
    return {"results": out}


@mock_generator("safety_check")
def safety_check(inputs: dict[str, Any]) -> dict[str, Any]:
    text = inputs.get("text", "")
    flags = []
    for k in inputs.get("confidential", []):
        if k and k.lower() in text.lower():
            flags.append(
                {"type": "confidential", "text": k, "severity": "high", "note": "confidential keyword"}
            )
    for w in ("fraud", "scam", "lied", "stole"):
        if re.search(rf"\b{w}\b", text, re.I):
            flags.append(
                {"type": "accusation", "text": w, "severity": "high", "note": "unverified accusation"}
            )
    if re.search(r"\b(guaranteed returns|you should invest|buy this stock)\b", text, re.I):
        flags.append(
            {"type": "legal_financial_advice", "text": "investment advice tone", "severity": "medium"}
        )
    return {"flags": flags}


@mock_generator("carousel_writer")
def carousel_writer(inputs: dict[str, Any]) -> dict[str, Any]:
    facts = _fact_lines(inputs.get("sources", []), 6)
    lo = int(inputs.get("slides_min", 6))
    hook = "What actually changes for teams shipping LLM features"
    slides = [{"title": hook, "body": "Swipe for what it means in practice.", "alt": f"Title slide: {hook}"}]
    for f, _sid in facts[: lo - 2]:
        words = f.split()
        slides.append({"title": " ".join(words[:6]), "body": " ".join(words)[:160], "alt": f})
    generic = ["Test it on one real task", "Measure before you migrate", "Keep your eval set honest"]
    while len(slides) < lo - 1:
        g = generic[(len(slides) - 1) % len(generic)]
        slides.append({"title": g, "body": "Small experiments beat big rewrites.", "alt": g})
    slides.append(
        {
            "title": "What would you test first?",
            "body": "Tell me in the comments.",
            "cta": "Follow for more",
            "alt": "Closing slide asking what you would test first",
        }
    )
    claims = [{"sentence": f, "source_ids": [sid]} for f, sid in facts[: lo - 2]]
    tags = ["#ai", "#softwareengineering", "#llm"]
    return {
        "template": "carousel-minimal",
        "slides": slides,
        "caption": "The details are in the slides. What would you test first?\n\n" + " ".join(tags),
        "hashtags": tags,
        "claims": claims,
    }


@mock_generator("reel_writer")
def reel_writer(inputs: dict[str, Any]) -> dict[str, Any]:
    facts = _fact_lines(inputs.get("sources", []), 4)
    thesis = inputs.get("angle", {}).get("thesis", "One thing changed this week")
    beats, t = [], 2.0
    lines = [f for f, _ in facts] or [thesis]
    lines += [
        "Here is how I would test it on a real task.",
        "Measure it before you change your stack.",
        "Follow for the results.",
    ]
    for line in lines[:7]:
        dur = max(4.0, round(len(line.split()) / 2.5, 1))
        beats.append(
            {
                "t_start": t,
                "t_end": round(t + dur, 1),
                "voiceover": line,
                "on_screen": " ".join(line.split()[:6]),
                "shot": "screen recording of the release notes" if _NUM.search(line) else "talking head",
            }
        )
        t = round(t + dur, 1)
    while t < 30:
        beats.append(
            {
                "t_start": t,
                "t_end": round(t + 5, 1),
                "voiceover": "Small experiments beat big rewrites.",
                "on_screen": "Small experiments win",
                "shot": "b-roll of a terminal",
            }
        )
        t = round(t + 5, 1)
    return {
        "hook": {
            "t_start": 0,
            "t_end": 2,
            "voiceover": thesis[:90],
            "on_screen": thesis[:40],
            "shot": "close-up, fast cut",
        },
        "beats": beats,
        "caption": f"{thesis}. What would you test first?",
        "cover_text": thesis[:40],
        "hashtags": ["#ai", "#coding", "#llm"],
        "audio_mood": "calm, minimal electronic",
        "claims": [{"sentence": f, "source_ids": [sid]} for f, sid in facts],
    }


GENERIC_PARAS = [
    "Start with the smallest experiment that could change your mind. Pick one real task from your backlog, write down "
    "what good looks like, and run the new option next to the current one. Keep the setup boring so the comparison "
    "stays fair.",
    "Write the evaluation before you write the prompt. A short list of real inputs with expected outputs turns vague "
    "impressions into a number you can track. Grow the list every time production surprises you.",
    "Watch the operational cost, not only the quality. Latency, retries and the effort to keep the integration working "
    "decide whether a tool survives contact with a real team.",
    "Treat vendor benchmarks as a hypothesis. They tell you where to look, not what you will see on your own data. "
    "Your own tasks are the only benchmark that pays the bills.",
    "Keep the change reversible. Put the new component behind a flag, log enough to compare runs, and be ready to roll "
    "back without a meeting.",
]


@mock_generator("article_writer")
def article_writer(inputs: dict[str, Any]) -> dict[str, Any]:
    sources = inputs.get("sources", [])
    facts = _fact_lines(sources, 6)
    thesis = inputs.get("angle", {}).get("thesis", "A practical look")
    lo = int((inputs.get("words") or [1200, 2500])[0])
    parts = ["## What happened", "", *[f for f, _ in facts], "", "## Why it matters for engineers", ""]
    i = 0
    while len(" ".join(parts).split()) < lo - 120:
        parts += [GENERIC_PARAS[i % len(GENERIC_PARAS)], ""]
        if i % len(GENERIC_PARAS) == 1:
            parts += [
                "## Try it in ten minutes",
                "",
                "```python",
                "def evaluate(cases, run):",
                "    passed = sum(run(c['input']) == c['expected'] for c in cases)",
                "    return passed / len(cases)",
                "```",
                "",
            ]
        i += 1
    parts += ["## Takeaway", "", "Test the claim on your own work before you change your stack."]
    refs = [{"title": s["title"], "url": s["url"]} for s in sources if s.get("url")][:5]
    return {
        "seo_title": thesis[:68],
        "subtitle": "A practitioner's notes",
        "tldr": "What changed, what it means for engineers, and a ten-minute way to test it yourself.",
        "body_md": "\n".join(parts),
        "tags": ["ai", "llm", "engineering"],
        "references": refs,
        "cover_title": thesis[:60],
        "claims": [{"sentence": f, "source_ids": [sid]} for f, sid in facts],
    }


# ---------------- LAB ----------------
@mock_generator("spark_detect")
def spark_detect(inputs: dict[str, Any]) -> dict[str, Any]:
    stories = inputs.get("stories", [])
    prior = inputs.get("prior_art", [])
    existing = {e.lower() for e in inputs.get("existing", [])}
    ideas = []
    for s in stories[:6]:
        blob = (s["title"] + " " + s.get("summary", "")).lower()
        if inputs.get("capacity_guard"):
            kind = "practical"
        elif any(k in blob for k in ("protocol", "framework", "open-source", "release", "inference")):
            kind = "poc"
        elif any(k in blob for k in ("price", "pricing", "cut")):
            kind = "experiment"
        elif "injection" in blob or "security" in blob:
            kind = "weekend_build"
        else:
            continue
        title = {
            "poc": f"Small POC on {s['title'][:50]}",
            "experiment": f"Measure what {s['title'][:50]} saves you",
            "weekend_build": f"CLI guard inspired by {s['title'][:45]}",
            "practical": f"45-minute try-out: {s['title'][:45]}",
        }[kind]
        if title.lower() in existing:
            continue
        ev = [{"ref": s["id"], "why": "The development this idea builds on."}]
        others = [
            x
            for x in stories
            if x["id"] != s["id"]
            and set(re.findall(r"[a-z]{5,}", blob))
            & set(re.findall(r"[a-z]{5,}", (x["title"] + " " + x.get("summary", "")).lower()))
        ]
        if others:
            ev.append({"ref": others[0]["id"], "why": "An independent related signal."})
        pa = [
            a["id"]
            for a in prior
            if set(re.findall(r"[a-z]{5,}", a["title"].lower())) & set(re.findall(r"[a-z]{5,}", blob))
        ][:2]
        scores = {
            "impact": 6.5,
            "confidence": 6.0 + len(ev),
            "ease": 8.0 if kind in ("practical", "experiment") else 6.0,
            "personal_fit": 7.5,
            "learning_value": 7.0,
            "content_value": 7.5,
            "novelty": 6.0 - 1.5 * len(pa),
        }
        ideas.append(
            {
                "type": kind,
                "title": title,
                "one_liner": f"Turn '{s['title'][:60]}' into something you can run this week.",
                "evidence": ev,
                "problem": "Teams read about it but never measure it on their own work.",
                "persona": "A backend or AI engineer shipping LLM features",
                "why_now": s.get("summary", "")[:200],
                "solution": "A minimal tool or notebook that measures the claim on real tasks.",
                "mvp_scope": ["one command to run", "a results table", "README with setup"],
                "not_in_mvp": ["UI", "auth", "multi-tenant"],
                "stack": ["python", "fastapi", "one new: evals harness"],
                "effort": {"estimate": "1 day" if kind != "practical" else "45 min", "confidence": "medium"},
                "risks": ["results may not generalise beyond your tasks"],
                "moat": "Your own task data and eval set.",
                "validation_plan": [
                    "run on 10 real tasks",
                    "share the table in a post and ask who sees the same",
                ],
                "learning_skills": ["Evals & testing of LLM apps"],
                "content_plan": ["kickoff post", "results carousel"],
                "scores": scores,
                "prior_art_refs": pa,
            }
        )
        if len(ideas) >= 3:
            break
    return {"ideas": ideas}


@mock_generator("build_brief")
def build_brief(inputs: dict[str, Any]) -> dict[str, Any]:
    idea = inputs["idea"]
    ev = "\n".join(f"- {e['title']}: {e['url']}" for e in inputs.get("evidence", []))
    mvp = "\n".join(f"- {m}" for m in idea.get("mvp_scope", []))
    non = "\n".join(f"- {m}" for m in idea.get("not_in_mvp", []))
    brief = f"""# {idea["title"]}

## Goal
{idea["one_liner"]}

## User story
As {idea["persona"]}, I want {idea["solution"].lower()} so that {idea["problem"].lower()}

## Scope
{mvp}

## Non-goals
{non}

## Acceptance criteria
- [ ] Running the main command on the sample input produces the results table
- [ ] Tests pass with `make test`
- [ ] README explains setup in under 5 steps

## Stack
{", ".join(idea.get("stack", []))}

## Architecture sketch
```mermaid
flowchart LR
  input[Tasks] --> runner[Runner] --> results[Results table]
```

## Data model
- Task(id, input, expected)
- Result(task_id, output, passed, latency_ms)

## Milestones
1. Day 1: runner + one task end to end (check: one passing result row)
2. Day 2: ten tasks + results table (check: table renders)

## Test plan
Unit tests for the runner and scorer; one end-to-end run on sample tasks.

## Demo script
Run the command, show the table, explain one surprising result.

## Risks
{chr(10).join("- " + r for r in idea.get("risks", []))}

## Evidence
{ev}
"""
    claude = f"""# CLAUDE.md — {idea["title"]}

## Rules
- Keep the MVP scope in BRIEF.md; anything else goes to a follow-up list.
- Never invent facts or numbers in outputs; results come from actual runs.
- Small commits with conventional messages.

## Commands
- install: `uv sync`
- test: `uv run pytest`
- lint: `uv run ruff check .`
- run: `uv run python -m app`

## Definition of done
All acceptance criteria in BRIEF.md pass and the demo script works.
"""
    exp = ""
    if idea.get("type") in ("experiment", "practical"):
        exp = f"""# EXPERIMENT — {idea["title"]}

## Hypothesis
{idea["one_liner"]}

## Setup
Describe the environment and versions used.

## Dataset
10 real tasks from your backlog.

## Metrics
Pass rate, latency, cost per task.

## Procedure
1. Run baseline. 2. Run candidate. 3. Compare.

## Results
| Task | Baseline | Candidate | Notes |
|------|----------|-----------|-------|
"""
    return {"brief_md": brief, "claude_md": claude, "experiment_md": exp}


# ---------------- GYM / MOAT ----------------
def _words5(t: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", t.lower()))


@mock_generator("learn_next")
def learn_next(inputs: dict[str, Any]) -> dict[str, Any]:
    stories = inputs.get("stories", [])
    res = inputs.get("resources", [])
    items = []
    for c in inputs.get("candidates", [])[:3]:
        rel = [s["id"] for s in stories if _words5(c["name"]) & _words5(s["title"])][:2]
        why = (
            f"{c['name']} is a {c['durability']} skill with a gap of {c['target'] - c['current']} levels"
            + (
                " and it shows up in this week's news " + " ".join(f"[{r}]" for r in rel)
                if rel
                else "; this is a fundamentals gap, not driven by news"
            )
            + "."
        )
        items.append(
            {
                "skill": c["name"],
                "why": why,
                "evidence": rel,
                "ignore_instead": "New wrapper libraries around the same idea",
                "plan": {
                    "explainer_topic": c["name"],
                    "resources": [r["id"] for r in res if _words5(r["title"]) & _words5(c["name"])][:2],
                    "practical": f"Build a 45-minute exercise that uses {c['name'].lower()} on a real task",
                    "time_estimate": "3 hours this week",
                    "done_definition": f"You can explain {c['name'].lower()} to a colleague and pass the quiz cards",
                },
            }
        )
    return {"items": items, "ignore": ["Framework-of-the-week releases", "Leaderboard drama"]}


@mock_generator("explainer")
def explainer(inputs: dict[str, Any]) -> dict[str, Any]:
    topic, depth = inputs["topic"], inputs["depth"]
    known = inputs.get("known", [])
    src = inputs.get("sources", [])
    cite = [s["id"] for s in src][:2]
    news = (
        f"\n\nIn the news: {_compress(sents(src[0]['text'])[0]) if src and sents(src[0]['text']) else src[0]['title'] if src else ''} [{cite[0]}]"
        if cite
        else ""
    )
    bodies = {
        "plain": f"**{topic}** in plain words.\n\nThink of it like a well-organised kitchen: the right things are close at hand when you need them.\n\nIt matters because it changes how reliably a system answers.\n\nYou use it when the obvious approach is too slow or too vague.\n\nYou skip it when the problem is small enough to solve directly.",
        "engineer": f"## {topic}: how it works\n\nThe mechanism has three parts: an input step, a decision step and a check step.\n\n**Trade-offs:** more steps add latency and cost, but reduce silent failures.\n\n**When to use it:** when wrong answers are expensive.\n\n```python\ndef run(task, steps):\n    for step in steps:\n        task = step(task)\n    return task\n```",
        "deep": f"## {topic}: internals and limits\n\nAt depth, the behaviour depends on how errors compound across steps and how the check step is calibrated.\n\n**Limitations:** checks share blind spots with the generator; measure on held-out tasks.",
    }
    connects = (
        ("This connects to " + ", ".join(known[:3]) + ", which you already know well.")
        if known
        else "Rate your skills to see how this connects to what you know."
    )
    body = (
        bodies.get(depth, bodies["engineer"])
        + news
        + f"\n\n### How this connects to what you already know\n{connects}"
    )
    cards = [
        {
            "type": "qa",
            "front": f"What problem does {topic} solve?",
            "back": "It makes answers more reliable when the obvious approach is too slow or vague.",
        },
        {
            "type": "one_line",
            "front": f"Explain {topic} in one line.",
            "back": "Organise the work so the right information or check is applied at the right step.",
        },
        {
            "type": "scenario",
            "front": f"Your outputs are often wrong and errors are costly. Would you add {topic}? Why?",
            "back": "Yes: the added latency is worth fewer silent failures; measure on real tasks first.",
        },
    ]
    if depth != "plain":
        cards.append(
            {
                "type": "code",
                "front": "What does `run(task, steps)` return?",
                "back": "The task after every step has been applied in order.",
            }
        )
    return {"body_md": body, "connects_to": connects, "citations": cite, "cards": cards}


@mock_generator("moat_radar")
def moat_radar(inputs: dict[str, Any]) -> dict[str, Any]:
    st = inputs.get("stories", [])
    churn = [s for s in st if s.get("durability") == "churn"]
    fund = [s for s in st if s.get("durability") == "fundamental"]
    trend = [s for s in st if s.get("durability") == "trend"]

    def pt(s: dict[str, Any], claim: str) -> dict[str, Any]:
        return {"claim": claim, "evidence": [s["id"]], "reasoning": s["title"]}

    out: dict[str, Any] = {
        "commoditising": [pt(s, f"Commodity: {s['title'][:80]}") for s in (churn + trend)[:3]],
        "appreciating": [pt(s, f"Appreciating: skills around {s['title'][:70]}") for s in fund[:3]],
        "for_you": {
            "know": [pt(s, s["title"][:90]) for s in (fund + trend)[:3]],
            "learn": [pt(s, f"Learn the fundamentals behind {s['title'][:60]}") for s in fund[:3]],
            "stop": [pt(s, f"Stop tracking every version of {s['title'][:50]}") for s in churn[:1]],
        },
        "for_builders": [
            pt(s, "Defensibility moves to evaluation data and workflow trust") for s in fund[:1]
        ],
        "predictions": [
            {
                "text": "At least one more open-weights model release will claim parity on coding benchmarks within 90 days.",
                "revisit_in_days": 90,
            }
        ],
        "prediction_reviews": [
            {"id": p["id"], "outcome": "unclear", "evidence": [], "note": "Not enough evidence yet."}
            for p in inputs.get("previous", [])
        ],
    }
    return out


@mock_generator("review_summary")
def review_summary(inputs: dict[str, Any]) -> dict[str, Any]:
    st = inputs.get("stories", [])
    if not st:
        return {"summary": "A quiet period: nothing important cleared the bar."}
    lead = "; ".join(f"{s['title']} [{s['id']}]" for s in st[:3])
    fund = sum(1 for s in st if s.get("durability") == "fundamental")
    return {
        "summary": f"The {'week' if inputs.get('kind') == 'weekly' else 'month'} was shaped by: {lead}. "
        f"{fund} of the top stories look like durable shifts rather than churn."
    }


@mock_generator("metrics_learnings")
def metrics_learnings(inputs: dict[str, Any]) -> dict[str, Any]:
    s = inputs.get("summary", {})
    findings, changes = [], {}
    for var, groups in (s.get("breakdowns") or {}).items():
        if len(groups) >= 2:
            best = max(groups, key=lambda k: groups[k]["median_engagement"])
            n = groups[best]["n"]
            findings.append(
                f"{var}={best} had the highest median engagement ({n} posts"
                + (", small sample" if groups[best]["caution"] else "")
                + ")"
            )
            if var == "length_bucket" and best == "short":
                changes["max_words_per_line"] = 12
    if not findings:
        findings = ["Not enough measured posts yet to change anything."]
    return {
        "findings": findings,
        "voice_rule_changes": changes or {"prefer_hook": "surprising_number"},
        "add_banned_phrases": [],
        "best_times": {},
        "angle_preferences": ["practitioner"],
        "caveats": "Small samples; treat as directional and re-test one variable at a time.",
    }


@mock_generator("ask")
def ask(inputs: dict[str, Any]) -> dict[str, Any]:
    q = _words5(inputs["question"])
    chunks = inputs.get("chunks", [])
    rel = [c for c in chunks if len(q & _words5(c["title"] + " " + c["text"])) >= max(1, min(2, len(q) // 3))]
    if not rel:
        return {"answer": "The retrieved notes do not answer this.", "insufficient": True}
    parts = []
    for c in rel[:3]:
        ss = [x for x in sents(c["text"]) if _words5(x) & q] or sents(c["text"])[:1]
        if ss:
            parts.append(f"{_compress(ss[0])} [{c['id']}]")
    if inputs.get("mode") == "compare":
        parts.insert(0, "Here is how they compare, based on your sources:")
    return {"answer": " ".join(parts), "insufficient": False}


# ---------------- benchmark labelling (ADR-026): deterministic stand-ins, never product output ----------------
@mock_generator("bench_label_items")
def bench_label_items(inputs: dict[str, Any]) -> dict[str, Any]:
    prof = inputs.get("profile", {})
    core = _words5(" ".join(prof.get("core", [])))
    adj = _words5(" ".join(prof.get("adjacent", [])))
    out = []
    for it in inputs.get("items", []):
        w = _words5(it["title"] + " " + it["text"])
        c, a = len(w & core), len(w & adj)
        rel = 3 if c >= 4 else 2 if c >= 2 else 1 if c + a >= 1 else 0
        ring = "core" if c >= 2 else "adjacent" if a >= 1 else "wide" if c else "none"
        out.append(
            {"id": it["id"], "relevance": rel, "ring": ring, "reason": f"{c} core / {a} adjacent terms"}
        )
    return {"labels": out}


@mock_generator("bench_label_pairs")
def bench_label_pairs(inputs: dict[str, Any]) -> dict[str, Any]:
    out = []
    for p in inputs.get("pairs", []):
        a, b = _words5(p["a"]["title"]), _words5(p["b"]["title"])
        j = len(a & b) / max(1, len(a | b))
        out.append({"id": p["id"], "same_event": j >= 0.35, "reason": f"title overlap {j:.2f}"})
    return {"pairs": out}


@mock_generator("bench_questions")
def bench_questions(inputs: dict[str, Any]) -> dict[str, Any]:
    out = []
    for it in inputs.get("items", []):
        words = sorted(_words5(it["title"]), key=lambda x: (-len(x), x))[:3]
        out.append({"id": it["id"], "question": "What happened with " + " ".join(words) + "?"})
    return {"questions": out}
