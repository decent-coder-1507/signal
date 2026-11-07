"""Visual asset renderer (§7.7): HTML/CSS templates → PNG per slide + combined PDF via Playwright (Chromium).

Accessibility gates: WCAG contrast ≥ 4.5:1 between text and background colours of the brand kit, minimum computed
font size ≥ 28 px at 1080 px width (checked in the rendered page), alt text per slide.
Locally Playwright drives the installed Google Chrome (`SIGNAL_RENDER_CHANNEL`, default "chrome"); CI uses bundled
Chromium (ADR-010).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from signal_core.settings import REPO_ROOT, get_settings

TEMPLATES = Path(__file__).parent / "templates"
SIZES = {
    "carousel": (1080, 1350),
    "quote_card": (1080, 1350),
    "stat_card": (1080, 1350),
    "reel_cover": (1080, 1920),
    "article_cover": (1600, 840),
}
MIN_FONT_PX = 28
MIN_CONTRAST = 4.5
MERMAID_JS = REPO_ROOT / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"

_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))


class RenderError(RuntimeError):
    pass


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def ch(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(fg: str, bg: str) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def palette(brand: dict[str, Any], dark: bool = True) -> dict[str, str]:
    """High-contrast big-type palette from the brand kit (dark slides by default, like most carousels)."""
    if dark:
        return {
            "bg": brand.get("primary", "#111827"),
            "fg": "#FFFFFF",
            "accent": brand.get("accent", "#F59E0B"),
            "muted": "#D1D5DB",
        }
    return {
        "bg": brand.get("background", "#FFFFFF"),
        "fg": brand.get("primary", "#111827"),
        "accent": brand.get("accent", "#B45309"),
        "muted": "#374151",
    }


def check_contrast(pal: dict[str, str]) -> dict[str, float]:
    out = {
        "fg_bg": contrast(pal["fg"], pal["bg"]),
        "muted_bg": contrast(pal["muted"], pal["bg"]),
        "accent_bg": contrast(pal["accent"], pal["bg"]),
    }
    bad = {k: v for k, v in out.items() if v < MIN_CONTRAST}
    if bad:
        raise RenderError(f"contrast below {MIN_CONTRAST}:1 — {bad}")
    return out


@dataclass
class RenderResult:
    pngs: list[Path]
    pdf: Path | None
    alt: list[str]
    contrast: dict[str, float]
    min_font_px: float
    size: tuple[int, int]
    meta: dict[str, Any] = field(default_factory=dict)


async def render(
    kind: str,
    template: str,
    slides: list[dict[str, Any]],
    brand: dict[str, Any],
    out_dir: Path,
    dark: bool = True,
    pdf: bool = True,
) -> RenderResult:
    from playwright.async_api import async_playwright

    if kind not in SIZES:
        raise RenderError(f"unknown asset kind {kind!r}")
    w, h = SIZES[kind]
    pal = palette(brand, dark)
    contrast_report = check_contrast(pal)
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl = _env.get_template(f"{template}.html.j2")
    channel = os.environ.get("SIGNAL_RENDER_CHANNEL", "" if os.environ.get("CI") else "chrome") or None
    pngs: list[Path] = []
    pages_html: list[str] = []
    min_font = 999.0
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=channel, headless=True)
        try:
            page = await browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            for i, s in enumerate(slides, 1):
                html = tpl.render(
                    slide=s, index=i, total=len(slides), brand=brand, p=pal, w=w, h=h, min_font=MIN_FONT_PX
                )
                pages_html.append(html)
                await page.set_content(html, wait_until="load")
                if s.get("mermaid") and MERMAID_JS.exists():
                    await page.add_script_tag(path=str(MERMAID_JS))
                    await page.evaluate(
                        "async () => { mermaid.initialize({startOnLoad:false, theme:'dark'});"
                        " await mermaid.run({querySelector: '.mermaid'}); }"
                    )
                fmin = await page.evaluate(
                    """() => { let m = 999; for (const el of document.querySelectorAll('body *')) {
                        const t = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
                        if (!t || el.closest('svg')) continue;
                        m = Math.min(m, parseFloat(getComputedStyle(el).fontSize)); } return m; }"""
                )
                min_font = min(min_font, float(fmin))
                path = out_dir / f"slide-{i:02d}.png"
                await page.screenshot(path=str(path), clip={"x": 0, "y": 0, "width": w, "height": h})
                pngs.append(path)
            pdf_path = None
            if pdf:
                pdf_path = out_dir / ("carousel.pdf" if kind == "carousel" else f"{kind}.pdf")
                joined = "".join(
                    f'<div style="page-break-after:always;width:{w}px;height:{h}px;overflow:hidden">{x}</div>'
                    for x in pages_html
                )
                await page.set_content(
                    f"<html><body style='margin:0'>{joined}</body></html>", wait_until="load"
                )
                await page.pdf(
                    path=str(pdf_path),
                    width=f"{w}px",
                    height=f"{h}px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
        finally:
            await browser.close()
    if min_font < MIN_FONT_PX:
        raise RenderError(f"text rendered at {min_font}px; minimum is {MIN_FONT_PX}px at {w}px width")
    alt = [
        s.get("alt") or f"Slide {i}: {s.get('title', '')}. {s.get('body', '')}".strip()
        for i, s in enumerate(slides, 1)
    ]
    return RenderResult(pngs, pdf_path, alt, contrast_report, min_font, (w, h))


def assets_dir(draft_id: str) -> Path:
    return get_settings().data_dir / "assets" / draft_id
