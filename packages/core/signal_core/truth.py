"""Truthfulness validators (§9.8) — the most important product rule.

- quote_span must be a verbatim substring of the item text (whitespace/quote-style normalised only).
- every factual sentence in generated text carries [id] citations that resolve to stored items or raw-material ids.
- only URLs that exist in the DB (or a curated resource list) may appear in outputs.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
CITE = re.compile(r"\[([0-9a-fA-F-]{8,36}|r:[0-9a-fA-F-]{8,36})\]")
URL = re.compile(r"https?://[^\s)\]>\"']+")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def norm(s: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFKC", s).translate(_QUOTES)).strip()


def is_verbatim(span: str, text: str, min_words: int = 3) -> bool:
    span_n = norm(span)
    if len(span_n.split()) < min_words:
        return False
    return span_n in norm(text) or span_n.lower() in norm(text).lower()


@dataclass
class FactCheck:
    kept: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)


def validate_key_facts(facts: Iterable[dict[str, str]], text: str) -> FactCheck:
    out = FactCheck()
    for f in facts:
        (out.kept if is_verbatim(f.get("quote_span", ""), text) else out.rejected).append(f)
    return out


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text.strip()) if s.strip()]


@dataclass
class CitationReport:
    ok: bool
    sentences: int
    uncited: list[str]
    unknown_ids: list[str]


# Sentences that carry no factual claim and need no citation.
_NON_FACTUAL = re.compile(
    r"^(low personal relevance|it is (too )?early to|it is (still )?unclear|details are (still )?unclear"
    r"|nothing (else )?(is )?known|no further details)",
    re.I,
)


def check_citations(text: str, allowed_ids: set[str], require_every_sentence: bool = True) -> CitationReport:
    uncited: list[str] = []
    unknown: list[str] = []
    sents = sentences(text)
    for s in sents:
        ids = CITE.findall(s)
        if not ids:
            if require_every_sentence and not _NON_FACTUAL.match(s):
                uncited.append(s)
            continue
        unknown.extend(i for i in ids if i.removeprefix("r:") not in allowed_ids and i not in allowed_ids)
    return CitationReport(not uncited and not unknown, len(sents), uncited, sorted(set(unknown)))


def strip_unknown_citations(text: str, allowed_ids: set[str]) -> str:
    return CITE.sub(lambda m: m.group(0) if m.group(1).removeprefix("r:") in allowed_ids else "", text)


def drop_uncited_sentences(text: str, allowed_ids: set[str]) -> str:
    """Last line of defence: remove factual sentences that do not cite a known source."""
    keep = []
    for s in sentences(strip_unknown_citations(text, allowed_ids)):
        if CITE.search(s) or _NON_FACTUAL.match(s):
            keep.append(s)
    return " ".join(keep)


def urls_in(text: str) -> list[str]:
    return [u.rstrip(".,;") for u in URL.findall(text)]


def disallowed_urls(text: str, whitelist: set[str]) -> list[str]:
    from signal_core.radar.normalise import canonical_url

    wl = {canonical_url(u) for u in whitelist}
    return [u for u in urls_in(text) if canonical_url(u) not in wl]


def remove_disallowed_urls(text: str, whitelist: set[str]) -> str:
    for u in disallowed_urls(text, whitelist):
        text = text.replace(u, "[link removed: not in sources]")
    return text
