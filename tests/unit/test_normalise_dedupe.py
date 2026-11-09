import pytest

from signal_core.embeddings import MockEmbeddingProvider
from signal_core.radar.dedupe import containment, hamming, shingles, simhash
from signal_core.radar.normalise import canonical_url, infer_content_type, normalise, strip_html
from signal_core.radar.prefilter import ProfileVec, prefilter


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://www.Example.com/a/b/?utm_source=x&id=2&fbclid=1#frag", "https://www.example.com/a/b?id=2"),
        ("https://amp.example.com/tech/story/amp", "https://example.com/tech/story"),
        ("https://example.com/story.amp.html", "https://example.com/story.html"),
        ("https://news.ycombinator.com/item?id=123&utm_medium=x", "https://news.ycombinator.com/item?id=123"),
        ("https://m.example.com/path/", "https://example.com/path"),
        ("https://example.com:443//a//b?b=2&a=1", "https://example.com/a/b?a=1&b=2"),
        ("https://www.youtube.com/watch?v=abc&si=track", "https://www.youtube.com/watch?v=abc"),
    ],
)
def test_canonical_url(raw: str, expected: str) -> None:
    assert canonical_url(raw) == expected


def test_canonical_url_is_idempotent() -> None:
    u = "http://Example.com/x/?utm_campaign=y&q=1"
    assert canonical_url(canonical_url(u)) == canonical_url(u)


def test_content_type_inference() -> None:
    assert infer_content_type("https://arxiv.org/abs/2611.01234", None) == "paper"
    assert infer_content_type("https://github.com/a/b/releases/tag/v1", None) == "release"
    assert infer_content_type("https://github.com/a/b", None) == "repo"
    assert infer_content_type("https://www.youtube.com/watch?v=1", None) == "video"
    assert infer_content_type("https://example.com/post", "podcast") == "podcast"
    assert infer_content_type("https://example.com/post", None) == "article"


def test_normalise_prefers_longer_body_and_cleans_html() -> None:
    n = normalise(
        "https://ex.com/a?utm_source=x", " Title &amp; more ", "<p>Short <b>summary</b></p>", "", None
    )
    assert n.title == "Title & more" and n.text == "Short summary" and n.word_count == 2
    assert n.canonical_url == "https://ex.com/a" and len(n.url_hash) == 64
    assert strip_html("<div>a<br/>b</div>") == "a b"


TEXT = (
    "Nimbus AI released Nimbus-4 on Tuesday. The company says it scores 71.2% on SWE-bench Verified. "
    "It supports a context window of 400,000 tokens and costs $3 per million input tokens."
)


def test_simhash_near_duplicates_are_close_and_distinct_texts_far() -> None:
    a = simhash(TEXT)
    b = simhash(TEXT + " This article originally appeared on a partner site.")
    c = simhash(
        "A cricket league announced its new season schedule with matches in eight cities and new teams."
    )
    assert hamming(a, a) == 0
    assert hamming(a, b) < hamming(a, c)
    assert -(2**63) <= a < 2**63  # fits BIGINT


def test_containment_catches_boilerplate_appends() -> None:
    a, b = shingles(TEXT), shingles(TEXT + " Republished with permission.")
    assert containment(a, b) == 1.0
    assert containment(a, shingles("totally different words about cooking pasta at home tonight")) == 0.0


async def test_prefilter_keywords_plurals_and_blocklist() -> None:
    emb = MockEmbeddingProvider()
    [v] = await emb.embed(["ai engineering: agent, eval"])
    profile = [ProfileVec("ai-engineering", "core", 1.0, v, ["agent", "eval"])]
    [item] = await emb.embed(["New agents framework with evals"])
    r = prefilter(item, "New agents framework with evals", "body", profile, ["crypto price prediction"], [])
    assert r.score >= 0.4 and {"agents", "evals"} <= set(r.keyword_hits) and not r.blocked
    [lone] = await emb.embed(["Archive files name former agents"])
    weak = prefilter(lone, "Archive files name former agents", "history", profile, [], [])
    assert weak.score < r.score / 1.5  # a single generic one-word hit is weak evidence
    r2 = prefilter(item, "Crypto price prediction for agents", "x", profile, ["crypto price prediction"], [])
    assert r2.blocked and r2.score == 0.0


def test_canonical_url_tolerates_malformed_ports_from_scraped_text() -> None:
    # A real article mentioned "http://localhost:11434." — one bad link must never crash the pipeline.
    assert canonical_url("http://localhost:11434.") == "https://localhost/"
    assert canonical_url("https://example.com:8443/a/") == "https://example.com:8443/a"
