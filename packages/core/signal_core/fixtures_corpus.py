"""Deterministic fixture corpus for tests and mock-mode demo (§18).

ALL entities are fictional (Nimbus AI, Orchid Labs, Kestrel, Tessera …) so demo data can never be mistaken
for real news. Every item is labelled with its event so clustering purity and dedupe recall can be measured.

`build(base)` returns a URL → (content_type, bytes) map for a FixtureTransport, plus labels.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from xml.sax.saxutils import escape

import httpx

DEMO_NOTE = "Demo data: fictional companies and events generated for SIGNAL mock mode."


@dataclass
class FItem:
    source: str  # fixture source key
    event: str  # cluster label ("noise:*" = should be prefiltered out)
    title: str
    body: str
    url: str
    hours_ago: float
    author: str = "Staff"
    meta: dict[str, object] = field(default_factory=dict)


# Shared fact sentences per event: rewrites reuse them, so quote spans and clustering are realistic.
F = {
    "nimbus4": [
        "Nimbus AI released Nimbus-4, its new flagship language model, on Tuesday.",
        "The company says Nimbus-4 scores 71.2% on SWE-bench Verified, up from 58.9% for Nimbus-3.",
        "Nimbus-4 supports a context window of 400,000 tokens.",
        "API pricing is $3 per million input tokens and $15 per million output tokens.",
        "Nimbus AI has not published independent evaluations; the benchmark figures are self-reported.",
    ],
    "orchid70b": [
        "Orchid Labs published Orchid-70B, an open-weights model released under the Apache 2.0 license.",
        "Orchid Labs says the model was trained on 18 trillion tokens.",
        "Orchid-70B is available on the Orchid Hub with quantised 4-bit variants for single-GPU inference.",
        "The model card reports 64.5% on a held-out coding benchmark maintained by the lab.",
    ],
    "kestrel2": [
        "Kestrel 2.0, the open-source coding agent, adds a plan-then-execute mode and sandboxed shell access.",
        "The release notes say Kestrel 2.0 cuts median task time by 30% on the project's internal suite.",
        "Kestrel now supports the Agent Context Protocol for connecting external tools.",
    ],
    "tessera": [
        "Tessera 1.0, an open-source inference server, reached its first stable release.",
        "Tessera adds paged KV-cache management and speculative decoding enabled by default.",
        "The maintainers report 2.1x higher throughput than Tessera 0.9 on a 70B model at batch size 32.",
    ],
    "acp": [
        "Version 1.1 of the Agent Context Protocol specification was published by its steering group.",
        "ACP 1.1 adds streaming tool results and a standard authorisation flow for remote servers.",
        "The steering group says ACP 1.1 is backward compatible with 1.0 clients.",
    ],
    "verifier": [
        "A new paper proposes verifier loops for retrieval-augmented generation.",
        "The authors report that verifier loops reduce unsupported answers by 41% on three QA datasets.",
        "The method adds one extra model call per answer to check each claim against retrieved passages.",
    ],
    "nimbusprice": [
        "Nimbus AI cut API prices for Nimbus-3 by 50% effective immediately.",
        "Input tokens for Nimbus-3 now cost $1 per million.",
        "The company said the cut reflects lower serving costs on its new inference cluster.",
    ],
    "lumen": [
        "Lumen DB 2.4 adds hybrid search that combines vector similarity with BM25 keyword ranking.",
        "Lumen DB 2.4 also ships HNSW index builds that run 3x faster on large collections.",
    ],
    "rupeelend": [
        "RupeeLend, a Bengaluru lending startup, raised $40 million in a Series B round.",
        "RupeeLend says it will use the funding to expand its AI underwriting team.",
        "The round was led by a fictional fund named Banyan Ventures.",
    ],
    "dsbpolicy": [
        "The Digital Standards Board published draft guidelines for AI systems used in lending and hiring.",
        "The draft requires documented human review for automated decisions above a risk threshold.",
        "Public comments on the draft are open for 45 days.",
    ],
    "voltachip": [
        "Volta Semi announced the VX-2 accelerator for AI inference workloads.",
        "Volta Semi claims the VX-2 delivers 1.8x performance per watt compared with its previous chip.",
        "Volume shipments of the VX-2 are planned for the second quarter of next year.",
    ],
    "jobs": [
        "A hiring survey of 1,200 engineering managers found demand rising for engineers with evaluation and reliability skills for AI systems.",
        "The survey reports that 38% of teams plan to hire for AI platform roles in the next six months.",
    ],
    "injection": [
        "Security researchers disclosed a prompt injection technique that makes coding agents run commands hidden in repository files.",
        "The researchers say the attack worked against three popular coding agents in default configurations.",
        "Vendors recommend running agents in sandboxes and requiring approval for shell commands.",
    ],
    "pgflux": [
        "PgFlux 3.0, an open-source Postgres extension, adds asynchronous I/O for sequential scans.",
        "The maintainers report up to 2.5x faster large table scans on NVMe storage.",
    ],
    "evals": [
        "An essay argues that teams shipping LLM features should build task-specific evaluation sets before tuning prompts.",
        "The author recommends starting with 50 real user examples and growing the set from production failures.",
    ],
    "tinyagent": [
        "tinyagent is a 300-line Python agent framework trending on GitHub.",
        "The project implements tool calling, retries and tracing with no external dependencies.",
    ],
}


def _txt(event: str, idx: list[int], frame: str) -> str:
    facts = F[event]
    return frame + " " + " ".join(facts[i] for i in idx if i < len(facts))


# Secondary outlets paraphrase rather than copy (names and numbers are kept verbatim), like real rewrites.
PARAPHRASE: dict[str, dict[str, str]] = {
    "news_a": {
        "released": "launched",
        "published": "put out",
        "says": "claims",
        "said": "stated",
        "supports": "offers",
        "adds": "introduces",
        "announced": "unveiled",
        "raised": "secured",
        "reports": "describes",
        "report": "describe",
        "available": "offered",
        "company": "firm",
        "new": "latest",
        "up from": "versus",
        "effective immediately": "starting today",
        "requires": "would mandate",
        "recommend": "advise",
        "reduce": "lower",
        "found": "showed",
        "plans": "intends",
        "planned": "scheduled",
        "the": "the",
        "is": "is",
        "has not": "hasn't",
        "use the funding to": "spend the new capital to",
    },
    "news_b": {
        "released": "shipped",
        "published": "issued",
        "says": "states",
        "said": "noted",
        "supports": "handles",
        "adds": "brings",
        "announced": "revealed",
        "raised": "closed",
        "reports": "cites",
        "report": "cite",
        "available": "downloadable",
        "company": "vendor",
        "new": "recent",
        "up from": "compared with",
        "effective immediately": "with immediate effect",
        "requires": "calls for",
        "recommend": "suggest",
        "reduce": "cut",
        "found": "indicated",
        "plans": "aims",
        "planned": "expected",
        "has not": "did not",
        "use the funding to": "put the money toward",
    },
    "analysis": {
        "released": "dropped",
        "says": "tells us",
        "supports": "comes with",
        "adds": "gains",
        "reports": "claims",
        "report": "claim",
        "company": "lab",
        "new": "fresh",
        "up from": "from",
        "reduce": "drop",
        "has not": "still hasn't",
    },
    "india_a": {
        "raised": "has raised",
        "says": "said",
        "published": "released",
        "requires": "mandates",
        "use the funding to": "deploy the capital to",
    },
    "india_b": {"raised": "bagged", "says": "told reporters", "use the funding to": "plough the funds into"},
    "hf": {"published": "uploaded", "available": "hosted"},
    "hf_papers": {"proposes": "introduces", "report": "show", "reduce": "lower"},
}
_WORDY: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(sorted({k for m in PARAPHRASE.values() for k in m}, key=len, reverse=True)) + r")\b"
)


def paraphrase(source: str, text: str) -> str:
    m = PARAPHRASE.get(source)
    if not m:
        return text
    return _WORDY.sub(lambda g: m.get(g.group(1), g.group(1)), text)


ITEMS: list[FItem] = [
    # E1 Nimbus-4: official + 2 news + analysis + HN (links official URL → merged signal)
    FItem(
        "official",
        "nimbus4",
        "Introducing Nimbus-4",
        _txt("nimbus4", [0, 1, 2, 3], "Today we are announcing our most capable model."),
        "https://nimbus.example/blog/introducing-nimbus-4",
        30,
    ),
    FItem(
        "news_a",
        "nimbus4",
        "Nimbus AI launches Nimbus-4 with 400K context window",
        _txt("nimbus4", [0, 2, 1, 3, 4], "Nimbus AI has a new model."),
        "https://technews-a.example/2026/11/nimbus-ai-launches-nimbus-4",
        28,
    ),
    FItem(
        "news_b",
        "nimbus4",
        "Nimbus-4 claims top SWE-bench score; pricing set at $3 per million tokens",
        _txt("nimbus4", [1, 3, 0, 4], "The benchmark race continues."),
        "https://devwire-b.example/nimbus-4-swe-bench",
        26,
    ),
    FItem(
        "analysis",
        "nimbus4",
        "Notes on Nimbus-4: what the 71.2% really means",
        _txt("nimbus4", [1, 4, 2], "I spent the evening reading the Nimbus-4 announcement."),
        "https://practitioner.example/2026/nimbus-4-notes",
        20,
    ),
    # E2 Orchid-70B
    FItem(
        "official",
        "orchid70b",
        "Orchid-70B: open weights, Apache 2.0",
        _txt("orchid70b", [0, 1, 2, 3], "We are releasing our largest open model."),
        "https://orchidlabs.example/news/orchid-70b",
        40,
    ),
    FItem(
        "news_a",
        "orchid70b",
        "Orchid Labs releases Orchid-70B as open weights",
        _txt("orchid70b", [0, 1, 2], "Another strong open-weights release."),
        "https://technews-a.example/2026/11/orchid-labs-orchid-70b-open-weights",
        38,
    ),
    FItem(
        "hf",
        "orchid70b",
        "Trending model: orchidlabs/Orchid-70B",
        _txt("orchid70b", [0, 2], "Trending on the hub."),
        "https://hub.example/orchidlabs/Orchid-70B",
        36,
        meta={"hf_likes": 2400},
    ),
    # E3 Kestrel 2.0
    FItem(
        "gh_releases",
        "kestrel2",
        "kestrel-dev/kestrel v2.0.0",
        _txt("kestrel2", [0, 1, 2], "Release notes."),
        "https://github.com/kestrel-dev/kestrel/releases/tag/v2.0.0",
        22,
    ),
    FItem(
        "news_b",
        "kestrel2",
        "Kestrel 2.0 coding agent adds plan-then-execute mode",
        _txt("kestrel2", [0, 2, 1], "Open-source coding agents keep improving."),
        "https://devwire-b.example/kestrel-2-coding-agent",
        18,
    ),
    # E4 Tessera
    FItem(
        "gh_releases",
        "tessera",
        "tessera-project/tessera v1.0.0",
        _txt("tessera", [0, 1, 2], "First stable release."),
        "https://github.com/tessera-project/tessera/releases/tag/v1.0.0",
        50,
    ),
    FItem(
        "analysis",
        "tessera",
        "Tessera 1.0 and the commoditisation of inference servers",
        _txt("tessera", [0, 1, 2], "Inference servers are converging on the same feature set."),
        "https://practitioner.example/2026/tessera-1",
        44,
    ),
    # E5 ACP 1.1
    FItem(
        "official",
        "acp",
        "Agent Context Protocol 1.1 released",
        _txt("acp", [0, 1, 2], "The steering group announces a new version."),
        "https://acp-spec.example/blog/acp-1-1",
        60,
    ),
    FItem(
        "analysis",
        "acp",
        "What changed in ACP 1.1 for tool builders",
        _txt("acp", [1, 2, 0], "If you maintain a tool server, read this."),
        "https://practitioner.example/2026/acp-1-1",
        55,
    ),
    # E6 paper (arXiv + HF daily)
    FItem(
        "arxiv",
        "verifier",
        "Verifier Loops for Grounded Retrieval-Augmented Generation",
        _txt("verifier", [0, 1, 2], "Abstract:"),
        "https://arxiv.example/abs/2611.01234",
        70,
        author="A. Rao, M. Chen",
    ),
    FItem(
        "hf_papers",
        "verifier",
        "Verifier Loops for Grounded Retrieval-Augmented Generation",
        _txt("verifier", [0, 1], "Daily paper pick."),
        "https://hub.example/papers/2611.01234",
        65,
        meta={"hf_upvotes": 87},
    ),
    # E7 price cut
    FItem(
        "official",
        "nimbusprice",
        "Lower prices for Nimbus-3",
        _txt("nimbusprice", [0, 1, 2], "We are passing on efficiency gains."),
        "https://nimbus.example/blog/nimbus-3-price-cut",
        10,
    ),
    FItem(
        "news_a",
        "nimbusprice",
        "Nimbus AI halves Nimbus-3 API prices",
        _txt("nimbusprice", [0, 1, 2], "Model prices keep falling."),
        "https://technews-a.example/2026/11/nimbus-halves-prices",
        8,
    ),
    # E8 Lumen DB
    FItem(
        "gh_releases",
        "lumen",
        "lumen-db/lumen v2.4.0",
        _txt("lumen", [0, 1], "Release notes."),
        "https://github.com/lumen-db/lumen/releases/tag/v2.4.0",
        33,
    ),
    # E9 RupeeLend (adjacent, India)
    FItem(
        "india_a",
        "rupeelend",
        "RupeeLend raises $40M Series B",
        _txt("rupeelend", [0, 1, 2], "Indian fintech funding news."),
        "https://indiatech-a.example/rupeelend-series-b",
        15,
    ),
    FItem(
        "india_b",
        "rupeelend",
        "Bengaluru's RupeeLend secures $40 million to grow AI underwriting",
        _txt("rupeelend", [0, 1], "Startup funding roundup."),
        "https://startupdesk-b.example/funding/rupeelend-40m",
        14,
    ),
    # E10 policy (adjacent)
    FItem(
        "india_a",
        "dsbpolicy",
        "Digital Standards Board drafts AI rules for lending and hiring",
        _txt("dsbpolicy", [0, 1, 2], "Policy update."),
        "https://indiatech-a.example/dsb-ai-draft-guidelines",
        48,
    ),
    FItem(
        "news_a",
        "dsbpolicy",
        "Draft AI guidelines would require human review of automated decisions",
        _txt("dsbpolicy", [1, 0, 2], "Regulators are moving."),
        "https://technews-a.example/2026/11/dsb-draft-ai-guidelines",
        46,
    ),
    # E11 chip (adjacent)
    FItem(
        "news_b",
        "voltachip",
        "Volta Semi unveils VX-2 inference accelerator",
        _txt("voltachip", [0, 1, 2], "Chip news."),
        "https://devwire-b.example/volta-vx-2",
        52,
    ),
    FItem(
        "news_a",
        "voltachip",
        "Volta Semi's VX-2 promises 1.8x performance per watt",
        _txt("voltachip", [1, 0, 2], "Hardware roundup."),
        "https://technews-a.example/2026/11/volta-vx-2",
        50,
    ),
    # E12 jobs (adjacent)
    FItem(
        "news_b",
        "jobs",
        "Survey: demand grows for AI reliability engineers",
        _txt("jobs", [0, 1], "Hiring trends."),
        "https://devwire-b.example/ai-reliability-hiring-survey",
        60,
    ),
    # E13 prompt injection (core security, 3 sources)
    FItem(
        "news_a",
        "injection",
        "Prompt injection hidden in repo files hijacks coding agents",
        _txt("injection", [0, 1, 2], "A new attack class."),
        "https://technews-a.example/2026/11/coding-agent-prompt-injection",
        12,
    ),
    FItem(
        "news_b",
        "injection",
        "Researchers show coding agents can be tricked into running hidden commands",
        _txt("injection", [0, 2, 1], "Security alert."),
        "https://devwire-b.example/coding-agents-hidden-commands",
        11,
    ),
    FItem(
        "analysis",
        "injection",
        "Sandbox your coding agent: notes on the repo-file injection disclosure",
        _txt("injection", [0, 2], "This one matters if you let agents run shell commands."),
        "https://practitioner.example/2026/sandbox-your-agent",
        6,
    ),
    # E14 PgFlux
    FItem(
        "gh_releases",
        "pgflux",
        "pgflux/pgflux v3.0.0",
        _txt("pgflux", [0, 1], "Release notes."),
        "https://github.com/pgflux/pgflux/releases/tag/v3.0.0",
        80,
    ),
    # E15 essay
    FItem(
        "analysis",
        "evals",
        "Build the eval set before you tune the prompt",
        _txt("evals", [0, 1], "A short essay on evaluation discipline for RAG and agents."),
        "https://practitioner.example/2026/evals-first",
        90,
    ),
    # E16 trending repo
    FItem(
        "gh_trending",
        "tinyagent",
        "someone/tinyagent: a 300-line Python agent framework",
        _txt("tinyagent", [0, 1], "Trending today."),
        "https://github.com/someone/tinyagent",
        5,
        meta={"gh_stars_period": 1450},
    ),
    # Noise (should be prefiltered out or score low)
    FItem(
        "news_b",
        "noise:celebrity",
        "Celebrity chef opens third restaurant",
        "A celebrity chef opened a third restaurant with a seasonal menu and a rooftop garden.",
        "https://devwire-b.example/celebrity-chef-restaurant",
        20,
    ),
    FItem(
        "news_a",
        "noise:crypto",
        "Crypto price prediction: analysts expect volatile week",
        "Crypto price prediction pieces expect a volatile week for tokens as traders watch macro data.",
        "https://technews-a.example/2026/11/crypto-price-prediction",
        9,
    ),
    FItem(
        "india_b",
        "noise:cricket",
        "Cricket league announces new season schedule",
        "The cricket league announced its new season schedule with matches in eight cities.",
        "https://startupdesk-b.example/cricket-schedule",
        30,
    ),
    FItem(
        "news_b",
        "noise:gadget",
        "Best phone cases of the year",
        "A roundup of colourful phone cases with drop protection and wallet slots.",
        "https://devwire-b.example/best-phone-cases",
        40,
    ),
]

for _it in ITEMS:
    _it.body = paraphrase(_it.source, _it.body)

# Syndicated near-duplicates: same text republished elsewhere with light edits (dedupe recall set).
SYNDICATE_FROM = [i for i in ITEMS if not i.event.startswith("noise")][:20]


def syndicated(i: FItem, n: int) -> FItem:
    return FItem(
        "syndicate",
        i.event,
        i.title.replace(":", " -") + " | Syndicated",
        i.body + " This article originally appeared on a partner site.",
        f"https://syndicate.example/story/{n}?utm_source=partner&utm_medium=feed",
        i.hours_ago - 0.5,
        meta={"syndicated_from": i.url},
    )


SYND_ITEMS = [syndicated(i, n) for n, i in enumerate(SYNDICATE_FROM)]
ALL_ITEMS = ITEMS + SYND_ITEMS

# Fixture sources (as they appear in a fixture sources list). URLs are .example (never resolvable).
FIXTURE_SOURCES = [
    {
        "type": "rss",
        "name": "Fixture: Official blogs",
        "key": "official",
        "url": "https://feeds.example/official.xml",
        "tier": 1,
    },
    {
        "type": "rss",
        "name": "Fixture: Tech News A",
        "key": "news_a",
        "url": "https://feeds.example/news-a.xml",
        "tier": 2,
    },
    {
        "type": "rss",
        "name": "Fixture: Dev Wire B",
        "key": "news_b",
        "url": "https://feeds.example/news-b.xml",
        "tier": 3,
    },
    {
        "type": "rss",
        "name": "Fixture: Practitioner blog",
        "key": "analysis",
        "url": "https://feeds.example/analysis.xml",
        "tier": 2,
    },
    {
        "type": "rss",
        "name": "Fixture: India Tech A",
        "key": "india_a",
        "url": "https://feeds.example/india-a.xml",
        "tier": 2,
        "ring": "adjacent",
    },
    {
        "type": "rss",
        "name": "Fixture: Startup Desk B",
        "key": "india_b",
        "url": "https://feeds.example/india-b.xml",
        "tier": 3,
        "ring": "adjacent",
    },
    {
        "type": "rss",
        "name": "Fixture: Syndication",
        "key": "syndicate",
        "url": "https://feeds.example/syndicate.xml",
        "tier": 3,
    },
    {
        "type": "rss",
        "name": "Fixture: Hub trending",
        "key": "hf",
        "url": "https://feeds.example/hub.xml",
        "tier": 2,
    },
    {
        "type": "rss",
        "name": "Fixture: Hub papers",
        "key": "hf_papers",
        "url": "https://feeds.example/hub-papers.xml",
        "tier": 2,
    },
    {
        "type": "rss",
        "name": "Fixture: arXiv",
        "key": "arxiv",
        "url": "https://feeds.example/arxiv.xml",
        "tier": 1,
    },
    {
        "type": "rss",
        "name": "Fixture: GitHub releases",
        "key": "gh_releases",
        "url": "https://feeds.example/releases.xml",
        "tier": 1,
    },
    {
        "type": "rss",
        "name": "Fixture: GitHub trending",
        "key": "gh_trending",
        "url": "https://feeds.example/trending.xml",
        "tier": 3,
    },
    {
        "type": "hn",
        "name": "Fixture: Hacker News",
        "key": "hn",
        "endpoint": "topstories",
        "min_points": 50,
        "tier": 3,
    },
    {
        "type": "rss",
        "name": "Fixture: Broken feed",
        "key": "broken",
        "url": "https://feeds.example/broken.xml",
        "tier": 3,
    },
]

HN_POSTS = [  # HN links the official Nimbus URL (merges signal) + the injection news + a low-score post
    {
        "id": 9001,
        "url": "https://nimbus.example/blog/introducing-nimbus-4?utm_source=hn",
        "title": "Nimbus-4",
        "score": 812,
        "descendants": 410,
        "hours_ago": 27,
    },
    {
        "id": 9002,
        "url": "https://technews-a.example/2026/11/coding-agent-prompt-injection",
        "title": "Prompt injection hidden in repo files hijacks coding agents",
        "score": 356,
        "descendants": 120,
        "hours_ago": 11,
    },
    {
        "id": 9003,
        "url": "https://blog.example/my-weekend-project",
        "title": "Show HN: my weekend project",
        "score": 12,
        "descendants": 3,
        "hours_ago": 3,
    },
]


def _rss(items: list[FItem], base: datetime, title: str) -> bytes:
    out = [
        f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{escape(title)}</title>'
        f"<link>https://feeds.example/</link><description>{escape(DEMO_NOTE)}</description>"
    ]
    for i in items:
        pub = format_datetime(base - timedelta(hours=i.hours_ago))
        out.append(
            f"<item><title>{escape(i.title)}</title><link>{escape(i.url)}</link>"
            f'<guid isPermaLink="false">{escape(i.url.split("?")[0])}</guid><pubDate>{pub}</pubDate>'
            f"<author>{escape(i.author)}</author><description>{escape(i.body)}</description></item>"
        )
    out.append("</channel></rss>")
    return "".join(out).encode()


def build(base: datetime | None = None) -> dict[str, tuple[str, bytes]]:
    base = base or datetime.now(UTC)
    routes: dict[str, tuple[str, bytes]] = {}
    for s in FIXTURE_SOURCES:
        if s["type"] == "rss" and s["key"] != "broken":
            items = [i for i in ALL_ITEMS if i.source == s["key"]]
            routes[str(s["url"])] = ("application/rss+xml", _rss(items, base, str(s["name"])))
    hn_base = "https://hacker-news.firebaseio.com/v0"
    routes[f"{hn_base}/topstories.json"] = (
        "application/json",
        json.dumps([p["id"] for p in HN_POSTS]).encode(),
    )
    for p in HN_POSTS:
        t = int((base - timedelta(hours=float(p["hours_ago"]))).timestamp())  # type: ignore[arg-type]
        routes[f"{hn_base}/item/{p['id']}.json"] = (
            "application/json",
            json.dumps(
                {
                    "id": p["id"],
                    "type": "story",
                    "by": "hnuser",
                    "time": t,
                    "title": p["title"],
                    "url": p["url"],
                    "score": p["score"],
                    "descendants": p["descendants"],
                }
            ).encode(),
        )
    return routes


class FixtureTransport(httpx.AsyncBaseTransport):
    """Serves the fixture corpus by URL; anything else is a 404 (no network in mock mode)."""

    def __init__(self, routes: dict[str, tuple[str, bytes]], fail: set[str] | None = None) -> None:
        self.routes = routes
        self.fail = fail or {"https://feeds.example/broken.xml"}
        self.requests: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0] if "firebaseio" in str(request.url) else str(request.url)
        self.requests.append(url)
        if url in self.fail:
            return httpx.Response(500, text="fixture: simulated outage", request=request)
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=request)
        hit = self.routes.get(url)
        if hit is None:
            return httpx.Response(404, text="fixture: not found", request=request)
        return httpx.Response(200, headers={"content-type": hit[0]}, content=hit[1], request=request)


def labels() -> dict[str, str]:
    """canonical-ish source URL → event label, for purity/recall measurement."""
    return {i.url: i.event for i in ALL_ITEMS}
