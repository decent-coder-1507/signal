"""normalise_item (§6.3 step 2): canonical URL, clean text, language, word count, content type."""

from __future__ import annotations

import hashlib
import html as htmlmod
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import trafilatura

TRACKING_PARAMS = re.compile(
    r"^(utm_\w+|fbclid|gclid|dclid|mc_cid|mc_eid|ref|ref_src|ref_url|source|cmpid|igshid|si|"
    r"_hsenc|_hsmi|mkt_tok|spm|share|s|t|guccounter|__twitter_impression)$",
    re.I,
)
IDENTITY_PARAMS = {"id", "v", "s", "t"}
KEEP_PARAMS_HOSTS = {"news.ycombinator.com", "www.youtube.com", "youtube.com"}  # ?id= / ?v= are identity
AMP_PATH = re.compile(r"(/amp/?$|/amp/(?=.))")
AMP_EXT = re.compile(r"\.amp(?=\.html?$)|\.amp$")
WS = re.compile(r"\s+")
TAG = re.compile(r"<[^>]+>")


def canonical_url(url: str) -> str:
    """Strip tracking params, fragments, AMP variants; lowercase scheme/host; drop default ports/trailing slash."""
    url = url.strip()
    if url.startswith("mid:"):
        return url
    p = urlsplit(url)
    scheme = (p.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    host = (p.hostname or "").lower()
    if host.startswith("amp.") and host.count(".") >= 2:
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    try:
        port_n = p.port
    except ValueError:  # malformed port in scraped text, e.g. "localhost:11434." at a sentence end
        port_n = None
    port = f":{port_n}" if port_n and port_n not in (80, 443) else ""
    path = AMP_EXT.sub("", AMP_PATH.sub("/", p.path or "/"))
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    q = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=False)
        if not TRACKING_PARAMS.match(k) or (host in KEEP_PARAMS_HOSTS and k in IDENTITY_PARAMS)
    ]
    q.sort()
    return urlunsplit((scheme, host + port, path, urlencode(q), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def strip_html(s: str) -> str:
    return WS.sub(" ", htmlmod.unescape(TAG.sub(" ", s or ""))).strip()


def extract_text(html: str, url: str | None = None) -> str:
    """trafilatura for real pages; fall back to tag stripping for short feed snippets."""
    if not html:
        return ""
    if len(html) > 600 and "<" in html:
        try:
            txt = trafilatura.extract(
                html, url=url, include_comments=False, include_tables=False, favor_precision=True
            )
        except Exception:
            txt = None
        if txt and len(txt) > 200:
            return WS.sub(" ", txt).strip()
    return strip_html(html)


def detect_language(text: str) -> str:
    sample = text[:2000]
    if len(sample) < 40:
        return "en"
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return str(detect(sample))[:8]
    except Exception:
        return "en"


CONTENT_TYPE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"arxiv\.org/(abs|pdf)/|huggingface\.co/papers/|openreview\.net|\.pdf$"), "paper"),
    (re.compile(r"github\.com/[^/]+/[^/]+/releases"), "release"),
    (re.compile(r"github\.com/[^/]+/[^/]+/?$|gitlab\.com/[^/]+/[^/]+/?$"), "repo"),
    (re.compile(r"youtube\.com/watch|youtu\.be/|vimeo\.com/"), "video"),
    (re.compile(r"producthunt\.com/posts/"), "launch"),
    (re.compile(r"news\.ycombinator\.com/item|reddit\.com/r/|x\.com/|twitter\.com/"), "post"),
]


def infer_content_type(url: str, hint: str | None) -> str:
    if hint:
        return hint
    for rx, t in CONTENT_TYPE_RULES:
        if rx.search(url):
            return t
    return "article"


@dataclass
class Normalised:
    canonical_url: str
    url_hash: str
    title: str
    text: str
    text_hash: str
    language: str
    word_count: int
    content_type: str


def normalise(url: str, title: str, summary: str, content_html: str, hint: str | None) -> Normalised:
    cu = canonical_url(url)
    body = extract_text(content_html, cu) if content_html else ""
    summary_txt = strip_html(summary)
    text = body if len(body) >= len(summary_txt) else summary_txt
    if body and summary_txt and summary_txt[:80] not in body:
        text = (summary_txt + "\n\n" + body).strip() if len(summary_txt) < 600 else text
    title = WS.sub(" ", htmlmod.unescape(title or "")).strip()[:1000]
    norm_for_hash = WS.sub(" ", text.lower())
    return Normalised(
        canonical_url=cu,
        url_hash=hashlib.sha256(cu.encode()).hexdigest(),
        title=title,
        text=text,
        text_hash=hashlib.sha256(norm_for_hash.encode()).hexdigest() if text else "",
        language=detect_language(title + ". " + text),
        word_count=len(text.split()),
        content_type=infer_content_type(cu, hint),
    )
