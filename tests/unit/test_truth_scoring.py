from types import SimpleNamespace

from signal_core.radar.cluster import compatible, entity_tags
from signal_core.radar.preference import predict, train
from signal_core.radar.scoring import credibility, mmr, signal_strength
from signal_core.truth import (
    check_citations,
    disallowed_urls,
    drop_uncited_sentences,
    first_sentence,
    is_verbatim,
    validate_key_facts,
)

ID1, ID2 = "0193a000-0000-7000-8000-000000000001", "0193a000-0000-7000-8000-000000000002"


def test_quote_span_must_be_verbatim() -> None:
    text = "Nimbus-4 supports a context window of 400,000 tokens.  Pricing is $3 per million input tokens."
    assert is_verbatim("a context window of 400,000 tokens", text)
    assert is_verbatim("Pricing is $3 per   million input tokens", text)  # whitespace-normalised only
    assert not is_verbatim("a context window of 500,000 tokens", text)
    assert not is_verbatim("tokens", text)  # too short to be evidence
    fc = validate_key_facts(
        [
            {"fact": "a", "quote_span": "context window of 400,000 tokens"},
            {"fact": "b", "quote_span": "costs $2 per million"},
        ],
        text,
    )
    assert len(fc.kept) == 1 and fc.rejected[0]["fact"] == "b"


def test_citations_resolve_and_uncited_sentences_are_dropped() -> None:
    allowed = {ID1, ID2}
    good = f"Nimbus released a model [{ID1}]. It is priced at $3 [{ID1}][{ID2}]."
    assert check_citations(good, allowed).ok
    bad = f"Nimbus released a model [{ID1}]. It beat every rival. Unknown cite [0193a000-0000-7000-8000-00000000dead]."
    rep = check_citations(bad, allowed)
    assert not rep.ok and rep.uncited == ["It beat every rival."] and rep.unknown_ids
    cleaned = drop_uncited_sentences(bad, allowed)
    assert "beat every rival" not in cleaned and "Unknown cite" not in cleaned and ID1 in cleaned


def test_url_whitelist() -> None:
    text = "See https://nimbus.example/blog/x?utm_source=a and https://made-up.example/y."
    assert disallowed_urls(text, {"https://nimbus.example/blog/x"}) == ["https://made-up.example/y"]


def test_entity_compatibility_separates_related_events() -> None:
    launch = entity_tags({"companies": ["Nimbus AI"], "models": ["Nimbus-4"]})
    price = entity_tags({"companies": ["Nimbus AI"], "models": ["Nimbus-3"]})
    report = entity_tags({"companies": ["Nimbus AI"]})
    assert not compatible(launch, price, 1)  # both specific, disjoint → different events
    assert compatible(launch, report, 1)  # company overlap, one side has no specific entity
    assert compatible([], launch, 1)


def _s(score: float, vec: list[float]) -> SimpleNamespace:
    return SimpleNamespace(final_score=score, centroid=vec)


def test_mmr_prefers_diversity() -> None:
    a, a2, b = _s(0.9, [1, 0, 0]), _s(0.89, [0.99, 0.1, 0]), _s(0.6, [0, 1, 0])
    picked = mmr([a, a2, b], 2, 0.7)  # type: ignore[arg-type]
    assert picked == [a, b]
    assert mmr([a, a2, b], 2, 1.0) == [a, a2]  # λ=1 → pure relevance  # type: ignore[arg-type]


def test_signal_and_credibility() -> None:
    one = [{"name": "Blog", "tier": 3, "role": "report", "signal_meta": {}}]
    many = [
        {"name": n, "tier": t, "role": r, "signal_meta": m}
        for n, t, r, m in [
            ("Official", 1, "primary", {}),
            ("News", 2, "report", {}),
            ("HN", 3, "reaction", {"hn_points_per_hour": 80}),
        ]
    ]
    assert signal_strength(many) > signal_strength(one)
    assert credibility(many) == 1.0 and credibility(one) < 0.35


def test_preference_model_learns_direction() -> None:
    X = [
        {"topic:agents", "src:A"},
        {"topic:agents", "src:B"},
        {"topic:agents"},
        {"topic:crypto", "src:C"},
        {"topic:crypto"},
        {"topic:crypto", "src:A"},
    ]
    y = [1, 1, 1, 0, 0, 0]
    w, b = train(X, y)
    assert predict(w, b, {"topic:agents"}) > 0.6 > 0.4 > predict(w, b, {"topic:crypto"})


def test_first_sentence_keeps_citations_in_live_and_mock_styles() -> None:
    a, b = "01a1bf2e-5371-768b-abbe-524abe9fc008", "01a1bf2e-50a0-706d-87d7-32543fc52aa3"
    live = f"Nimbus-4 scores 71.2% on SWE-bench at $3 per 1M tokens [{a}][{b}]. The figures are self-reported [{a}]."
    assert first_sentence(live) == f"Nimbus-4 scores 71.2% on SWE-bench at $3 per 1M tokens [{a}][{b}]."
    mock = f"Kestrel v2.0.0 adds sandboxing. [{a}] It also supports ACP. [{b}]"
    assert first_sentence(mock) == f"Kestrel v2.0.0 adds sandboxing. [{a}]"
    assert first_sentence("One sentence without a full stop") == "One sentence without a full stop"
    assert first_sentence(f"Only one. [{a}]") == f"Only one. [{a}]"
