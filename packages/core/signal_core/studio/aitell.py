"""AI-tell scanner (§7.8 gate 2), deterministic part.

Checks banned phrases/patterns/characters from the active voice profile, line length, emoji count, hashtag
count, word count, numbered "lessons" lists, bold-Unicode fonts and hashtag walls. Returns issues with character
spans so the editor can highlight them, plus live counters. (The LLM half of the scan is the grader's
`ai_phrases` list, ADR-018.)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff\U0001f900-\U0001f9ff⭐⭕✅❌]"
)
HASHTAG = re.compile(r"(?<![\w#])#[A-Za-z][\w]*")
BOLD_UNICODE = re.compile("[\U0001d400-\U0001d7ff]")
NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+\S", re.M)
URL = re.compile(r"https?://\S+")


@dataclass
class Issue:
    type: str
    message: str
    start: int = -1
    end: int = -1
    severity: str = "error"  # error blocks Ready; warn is advisory


@dataclass
class ScanResult:
    issues: list[Issue] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "issues": [asdict(i) for i in self.issues],
            "counters": self.counters,
            "passed": not self.blocking,
        }


def counters(text: str) -> dict[str, int]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    words = len(URL.sub("", text).split())
    return {
        "words": words,
        "chars": len(text),
        "lines": len(lines),
        "emoji": len(EMOJI.findall(text)),
        "hashtags": len(HASHTAG.findall(text)),
        "max_words_per_line": max((len(ln.split()) for ln in lines), default=0),
    }


def scan(
    text: str,
    voice_rules: dict[str, Any],
    banned_phrases: list[str],
    platform: str,
    platform_spec: dict[str, Any],
    fmt: str = "post",
) -> ScanResult:
    res = ScanResult(counters=counters(text))
    low = text.lower()
    for ph in banned_phrases:
        start = 0
        p = ph.lower()
        while (idx := low.find(p, start)) != -1:
            res.issues.append(Issue("banned_phrase", f'Banned phrase: "{ph}"', idx, idx + len(ph)))
            start = idx + len(ph)
    for pat in voice_rules.get("banned_patterns", []):
        for m in re.finditer(pat, text, re.I | re.M):
            res.issues.append(
                Issue("banned_pattern", f'Banned construction: "{m.group(0)}"', m.start(), m.end())
            )
    for ch in voice_rules.get("banned_chars", []):
        for m in re.finditer(re.escape(ch), text):
            res.issues.append(Issue("banned_char", f"Banned character {ch!r} (em dash)", m.start(), m.end()))
    for m in BOLD_UNICODE.finditer(text):
        res.issues.append(Issue("bold_unicode", "Bold Unicode font", m.start(), m.end()))
    nums = NUMBERED.findall(text)
    if len(nums) >= 3 and fmt == "post":
        res.issues.append(Issue("numbered_list", "Numbered lessons list (reads as AI-written)"))

    c = res.counters
    if fmt == "thread":
        return res  # per-post limits are checked by the thread checker
    emo = voice_rules.get("emoji", {})
    if platform == "linkedin":
        if c["emoji"] > int(emo.get("max", 3)):
            res.issues.append(Issue("emoji", f"{c['emoji']} emoji (max {emo.get('max', 3)})"))
        if c["emoji"] < int(emo.get("min", 0)):
            res.issues.append(
                Issue("emoji", f"{c['emoji']} emoji (min {emo.get('min', 1)})", severity="warn")
            )
        mwl = int(voice_rules.get("max_words_per_line", 15))
        offset = 0
        for ln in text.split("\n"):
            if len(ln.split()) > mwl + 5:  # most lines under 15 words; hard flag well above
                res.issues.append(
                    Issue(
                        "long_line",
                        f"Line has {len(ln.split())} words (aim ≤ {mwl})",
                        offset,
                        offset + len(ln),
                        "warn",
                    )
                )
            offset += len(ln) + 1
    tags = voice_rules.get("hashtags", {"max": 3})
    hmax = int(
        platform_spec.get("hashtags", [0, tags.get("max", 3)])[1]
        if isinstance(platform_spec.get("hashtags"), list)
        else tags.get("max", 3)
    )
    if c["hashtags"] > hmax:
        res.issues.append(Issue("hashtags", f"{c['hashtags']} hashtags (max {hmax})"))
    words = platform_spec.get("words")
    if words and fmt == "post":
        lo, hi = words
        if c["words"] > hi:
            res.issues.append(Issue("length", f"{c['words']} words (max {hi})"))
        elif c["words"] < lo:
            res.issues.append(Issue("length", f"{c['words']} words (target {lo}–{hi})", severity="warn"))
    if platform == "x" and fmt == "post":
        cmax = int(platform_spec.get("chars_max", 280))
        if c["chars"] > cmax:
            res.issues.append(Issue("length", f"{c['chars']} characters (max {cmax})"))
    return res


def scan_thread(
    posts: list[str], voice_rules: dict[str, Any], banned: list[str], spec: dict[str, Any]
) -> ScanResult:
    joined = "\n\n".join(posts)
    res = scan(joined, voice_rules, banned, "x", spec, fmt="thread")
    lo, hi = spec.get("thread_posts", [4, 10])
    if not lo <= len(posts) <= hi:
        res.issues.append(Issue("thread_length", f"{len(posts)} posts (target {lo}–{hi})"))
    cmax = int(spec.get("chars_max", 280))
    for i, p in enumerate(posts, 1):
        if len(p) > cmax:
            res.issues.append(Issue("length", f"post {i} has {len(p)} characters (max {cmax})"))
    res.counters["posts"] = len(posts)
    return res
