from signal_core.config import get_config
from signal_core.studio.aitell import counters, scan, scan_thread

RULES = {
    **get_config().voice.rules,
    "banned_patterns": get_config().voice.banned_patterns,
    "banned_chars": get_config().voice.banned_chars,
}
BANNED = get_config().voice.banned_phrases
LI = get_config().voice.platforms["linkedin"]
X = get_config().voice.platforms["x"]

GOOD = "\n\n".join(
    [
        "Nimbus says the new model scores 71.2% on SWE-bench Verified.",
        "I spent the evening reading the release notes.",
        "The benchmark looks strong, but benchmarks are a starting point.",
        "Our team will test it on ten real tickets this week.",
        "The context window is 400,000 tokens, which changes how we chunk documents.",
        "Pricing is $3 per million input tokens.",
        "That is cheap enough to try on a real workload without asking anyone.",
        "I will share the numbers once we have them.",
        "What would you test first? 🚀",
    ]
)


def test_clean_post_passes_with_counters() -> None:
    r = scan(GOOD, RULES, BANNED, "linkedin", LI)
    assert not r.blocking, [i.message for i in r.issues]
    assert r.counters["emoji"] == 1 and r.counters["hashtags"] == 0 and 80 <= r.counters["words"] <= 200


def test_banned_phrases_patterns_and_em_dash_have_spans() -> None:
    bad = "Here's the thing — this is a game-changer.\nIt's not hype, it's leverage."
    r = scan(bad, RULES, BANNED, "linkedin", LI)
    types = [i.type for i in r.blocking]
    assert types.count("banned_phrase") >= 3 and "banned_char" in types and "banned_pattern" in types
    i = next(i for i in r.issues if i.type == "banned_char")
    assert bad[i.start : i.end] == "—"


def test_hashtag_wall_numbered_list_and_bold_unicode() -> None:
    txt = "1. Lesson one\n2. Lesson two\n3. Lesson three\n#ai #ml #llm #agents #rag 𝐁𝐨𝐥𝐝"
    types = {i.type for i in scan(txt, RULES, BANNED, "linkedin", LI).blocking}
    assert {"numbered_list", "hashtags", "bold_unicode"} <= types


def test_x_length_and_thread_rules() -> None:
    assert any(i.type == "length" for i in scan("x" * 300, RULES, BANNED, "x", X).blocking)
    ok = scan_thread(["one post"] * 5, RULES, BANNED, X)
    assert not ok.blocking and ok.counters["posts"] == 5
    short = scan_thread(["only two", "posts"], RULES, BANNED, X)
    assert any(i.type == "thread_length" for i in short.blocking)


def test_counters() -> None:
    c = counters("Line one #ai\n\nLine two has more words 🚀🔥\nhttps://example.com/x")
    assert c == {**c, "lines": 3, "hashtags": 1, "emoji": 2}
