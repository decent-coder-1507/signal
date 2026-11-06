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
    factual = [s for s in ss if _NUM.search(s) or _CAP.search(s)]
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
