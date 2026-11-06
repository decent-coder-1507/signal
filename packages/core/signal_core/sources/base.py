"""Source adapter interface (§6.2). Every external source sits behind an adapter with a mockable HTTP layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from signal_core.sources.http import PoliteClient


@dataclass
class RawEntry:
    external_id: str
    url: str
    title: str
    published_at: datetime | None = None
    author: str | None = None
    summary: str = ""  # HTML or text from the feed
    content_html: str = ""  # full HTML when the feed carries it
    content_type_hint: str | None = None  # article|paper|repo|release|video|podcast|post|launch|newsletter
    signal_meta: dict[str, Any] = field(default_factory=dict)  # points, comments, stars, likes …
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    entries: list[RawEntry]
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class SourceSpec:
    """What adapters need from a Source row (decoupled from the ORM for testability)."""

    id: str
    type: str
    name: str
    url: str | None
    params: dict[str, Any]
    etag: str | None = None
    last_modified: str | None = None


class AdapterNotConfigured(RuntimeError):
    """Adapter needs credentials or a feature flag that is not set; the source is skipped, not failed."""


class Adapter(Protocol):
    async def __call__(self, spec: SourceSpec, http: PoliteClient) -> FetchResult: ...


AdapterFn = Callable[[SourceSpec, PoliteClient], Awaitable[FetchResult]]
ADAPTERS: dict[str, AdapterFn] = {}


def adapter(*types: str) -> Callable[[AdapterFn], AdapterFn]:
    def deco(fn: AdapterFn) -> AdapterFn:
        for t in types:
            ADAPTERS[t] = fn
        return fn

    return deco


def get_adapter(t: str) -> AdapterFn:
    from signal_core.sources import adapters  # noqa: F401  (registers adapters)

    if t not in ADAPTERS:
        raise AdapterNotConfigured(f"no adapter for source type '{t}'")
    return ADAPTERS[t]
