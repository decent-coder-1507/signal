"""Routers added per milestone are registered here so main.py stays stable."""

from __future__ import annotations

import importlib

from fastapi import FastAPI

MILESTONE_ROUTERS: list[str] = ["sources", "capture", "stories", "briefs", "studio", "lab"]


def register_all(app: FastAPI) -> None:
    for mod in MILESTONE_ROUTERS:
        app.include_router(importlib.import_module(f"signal_api.routers.{mod}").router)
