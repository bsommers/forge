#!/usr/bin/env python3
"""Deterministic Khazad-dûm Dwarven Forge SVG + PNG visual generator for MCP Server Forge.

Follows visual & documentation engineering standards:
- designing-logos-and-icons
- rendering-graphic-examples
- showcasing-graphics-in-docs

Theme: Khazad-dûm Dwarven Forge — deep volcanic basalt (#0b0604 -> #170b06 -> #090403),
angular dwarven diamond/chevron stone lattice (#ff6a00 / #d97706), glowing coal beds
(#991b1b -> #ea580c), roaring forge flames, horned dwarven anvils, runic warhammers,
molten gold channels (#fbbf24 / #ffd166), Mithril silver-white text (#f8fafc), and
tempered emerald (#10b981) PASS seals.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ROOT_ASSETS = ROOT / "assets"
DOCS_ASSETS = ROOT / "docs" / "assets"
ICONS_DIR = DOCS_ASSETS / "icons"
EXAMPLES_DIR = DOCS_ASSETS / "examples"

SERIF_STACK = "Georgia, 'Palatino Linotype', 'Times New Roman', serif"
SANS_STACK = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
MONO_STACK = "ui-monospace, 'Cascadia Code', 'Fira Code', Menlo, Consolas, monospace"

# Khazad-dûm Dwarven Forge RGB Palette for Pillow
RGB_BASALT_TOP = (11, 6, 4)
RGB_BASALT_MID = (23, 11, 6)
RGB_BASALT_BOT = (9, 4, 3)
RGB_SLAB = (20, 11, 8)
RGB_SLAB_INNER = (28, 15, 10)
RGB_MOLTEN_GOLD = (251, 191, 36)
RGB_BRIGHT_GOLD = (255, 209, 102)
RGB_WHITE_GOLD = (254, 240, 138)
RGB_FORGE_ORANGE = (249, 115, 22)
RGB_EMBER_CRIMSON = (239, 68, 68)
RGB_COAL_DARK = (153, 27, 27)
RGB_MITHRIL = (248, 250, 252)
RGB_STONE_TEXT = (203, 213, 225)
RGB_EMERALD = (16, 185, 129)
RGB_IRON_DARK = (30, 27, 26)
RGB_IRON_LIGHT = (71, 62, 57)


def esc(text: str) -> str:
    """Escape XML text content safely."""
    return html.escape(text, quote=False)


def svg_txt(
    x: float,
    y: float,
    text: str,
    fill: str,
    font: str,
    size: float,
    weight: str = "400",
    anchor: str = "",
    spacing: str = "",
    stroke: str = "",
    stroke_w: str = "",
) -> str:
    """Build compact, escaped SVG <text> element within 100-col budget."""
    attrs = [
        f'x="{x:g}"',
        f'y="{y:g}"',
        f'fill="{fill}"',
        f'font-family="{font}"',
        f'font-size="{size:g}"',
    ]
    if weight != "400":
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if spacing:
        attrs.append(f'letter-spacing="{spacing}"')
    if stroke:
        attrs.append(f'stroke="{stroke}"')
    if stroke_w:
        attrs.append(f'stroke-width="{stroke_w}"')
    return f"  <text {' '.join(attrs)}>{esc(text)}</text>"


def svg_poly(
    pts: str,
    fill: str,
    stroke: str = "",
    sw: str = "",
    extra: str = "",
) -> str:
    """Build SVG <polygon> element."""
    attrs = [f'points="{pts}"', f'fill="{fill}"']
    if stroke:
        attrs.append(f'stroke="{stroke}"')
    if sw:
        attrs.append(f'stroke-width="{sw}"')
    if extra:
        attrs.append(extra)
    return f"  <polygon {' '.join(attrs)} />"


def load_repo_stats() -> dict[str, Any]:
    """Read live manifest metadata so banners and diagrams stay synchronized with code."""
    manifest_path = ROOT / "forge-manifest.json"
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    tools = manifest.get("tools", [])
    return {
        "protocol": str(manifest.get("protocol_revision", "2026-07-28")),
        "server_name": str(manifest.get("server_name", "acme-incidents")),
        "version": str(manifest.get("version", "1.0.0")),
        "tool_count": len(tools) or 5,
    }


def oct_coords(
    cx: float, cy: float, r: float, rotate_deg: float = 22.5
) -> list[tuple[float, float]]:
    """Compute regular octagon vertex coordinates (flat-edged Khazad-dûm shield)."""
    pts: list[tuple[float, float]] = []
    for idx in range(8):
        ang = math.radians(rotate_deg + idx * 45.0)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def oct_points(cx: float, cy: float, r: float, rotate_deg: float = 22.5) -> str:
    """Format regular octagon points for SVG polygon attributes."""
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in oct_coords(cx, cy, r, rotate_deg))


def chamfer_rect_coords(
    x: float, y: float, w: float, h: float, c: float
) -> list[tuple[float, float]]:
    """Octagonal chamfered rectangle coordinates."""
    return [
        (x + c, y),
        (x + w - c, y),
        (x + w, y + c),
        (x + w, y + h - c),
        (x + w - c, y + h),
        (x + c, y + h),
        (x, y + h - c),
        (x, y + c),
    ]


def chamfer_rect_points(x: float, y: float, w: float, h: float, c: float) -> str:
    """Octagonal chamfered dwarven stone plaque polygon points."""
    coords = chamfer_rect_coords(x, y, w, h, c)
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)


def spark_field_svg(width: int, height: int, count: int = 28, seed_offset: int = 0) -> str:
    """Deterministic rising forge embers & golden sparks via golden-ratio layout."""
    palette = ("#ffd166", "#ff7b00", "#ff3b00", "#fbbf24")
    circles: list[str] = []
    phi = 0.61803398875
    for idx in range(count):
        n = idx + 1 + seed_offset * 7
        fx = (n * phi) % 1.0
        fy = ((n * phi * 1.73205) % 1.0) ** 0.78
        cx = 28.0 + fx * (width - 56.0)
        cy = height - 18.0 - fy * (height * 0.78)
        r = 1.3 + (idx % 4) * 0.85
        op = 0.32 + (1.0 - cy / height) * 0.45
        if cy > height * 0.72:
            op = min(0.88, op + 0.25)
        color = palette[idx % len(palette)]
        circles.append(
            f'    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{color}" fill-opacity="{op:.2f}" />'
        )
    return '  <g id="ember-sparks">\n' + "\n".join(circles) + "\n  </g>"


def coal_bed_svg(width: int, height: int) -> str:
    """Glowing coal bed fissures & faceted embers along the bottom hearth."""
    base_y = height - 26
    facets: list[str] = []
    step = max(48, width // 16)
    colors = ("#991b1b", "#dc2626", "#ea580c", "#f97316", "#fbbf24")
    for idx, x in enumerate(range(12, width - 24, step)):
        w = step - 8
        h_up = 8 + (idx % 3) * 5
        pts = (
            f"{x},{height} {x + 8},{base_y + 12 - h_up} "
            f"{x + w // 2},{base_y + 6 - (idx % 2) * 5} "
            f"{x + w - 6},{base_y + 14 - h_up} {x + w},{height}"
        )
        col = colors[idx % len(colors)]
        op = 0.28 + (idx % 3) * 0.10
        facets.append(f'    <polygon points="{pts}" fill="{col}" fill-opacity="{op:.2f}" />')
    y_top = int(height * 0.62)
    return (
        f'  <rect x="0" y="{y_top}" width="{width}" '
        f'height="{height - y_top}" fill="url(#coal-bed)" />\n'
        + '  <g id="coal-facets">\n'
        + "\n".join(facets)
        + "\n  </g>"
    )


def dwarven_corner_brackets_svg(x: float, y: float, w: float, h: float, arm: float = 34.0) -> str:
    """Double-beveled octagonal Khazad-dûm corner brackets in molten gold."""
    cham = arm * 0.42
    x2 = x + w
    y2 = y + h
    paths = [
        f"M {x},{y + arm} L {x},{y + cham} L {x + cham},{y} L {x + arm},{y}",
        f"M {x + 6},{y + arm - 4} L {x + 6},{y + cham + 3} "
        f"L {x + cham + 3},{y + 6} L {x + arm - 4},{y + 6}",
        f"M {x2 - arm},{y} L {x2 - cham},{y} L {x2},{y + cham} L {x2},{y + arm}",
        f"M {x2 - arm + 4},{y + 6} L {x2 - cham - 3},{y + 6} "
        f"L {x2 - 6},{y + cham + 3} L {x2 - 6},{y + arm - 4}",
        f"M {x},{y2 - arm} L {x},{y2 - cham} L {x + cham},{y2} L {x + arm},{y2}",
        f"M {x + 6},{y2 - arm + 4} L {x + 6},{y2 - cham - 3} "
        f"L {x + cham + 3},{y2 - 6} L {x + arm - 4},{y2 - 6}",
        f"M {x2 - arm},{y2} L {x2 - cham},{y2} L {x2},{y2 - cham} L {x2},{y2 - arm}",
        f"M {x2 - arm + 4},{y2 - 6} L {x2 - cham - 3},{y2 - 6} "
        f"L {x2 - 6},{y2 - cham - 3} L {x2 - 6},{y2 - arm + 4}",
    ]
    lines: list[str] = []
    for idx, d_str in enumerate(paths):
        sw = "3.0" if idx % 2 == 0 else "1.4"
        col = "#fbbf24" if idx % 2 == 0 else "#f97316"
        lines.append(
            f'    <path d="{d_str}" fill="none" stroke="{col}" '
            f'stroke-width="{sw}" stroke-linecap="square" />'
        )
    return '  <g id="khazad-brackets">\n' + "\n".join(lines) + "\n  </g>"


def common_svg_defs() -> str:
    """Shared Khazad-dûm Dwarven Forge gradients and stone lattice patterns."""
    return "\n".join(
        [
            "  <defs>",
            '    <linearGradient id="bg-basalt" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#0b0604" />',
            '      <stop offset="52%" stop-color="#170b06" />',
            '      <stop offset="100%" stop-color="#090403" />',
            "    </linearGradient>",
            '    <linearGradient id="coal-bed" x1="0%" y1="100%" x2="0%" y2="0%">',
            '      <stop offset="0%" stop-color="#991b1b" stop-opacity="0.72" />',
            '      <stop offset="38%" stop-color="#ea580c" stop-opacity="0.34" />',
            '      <stop offset="100%" stop-color="#090403" stop-opacity="0" />',
            "    </linearGradient>",
            '    <radialGradient id="hearth-aura" cx="50%" cy="58%" r="58%">',
            '      <stop offset="0%" stop-color="#ff5500" stop-opacity="0.24" />',
            '      <stop offset="48%" stop-color="#d97706" stop-opacity="0.10" />',
            '      <stop offset="100%" stop-color="#0b0604" stop-opacity="0" />',
            "    </radialGradient>",
            '    <linearGradient id="molten-gold" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#fef08a" />',
            '      <stop offset="45%" stop-color="#fbbf24" />',
            '      <stop offset="100%" stop-color="#ea580c" />',
            "    </linearGradient>",
            '    <linearGradient id="molten-channel" x1="0%" y1="50%" x2="100%" y2="50%">',
            '      <stop offset="0%" stop-color="#f97316" />',
            '      <stop offset="50%" stop-color="#ffd166" />',
            '      <stop offset="100%" stop-color="#fbbf24" />',
            "    </linearGradient>",
            '    <linearGradient id="flame-outer" x1="50%" y1="100%" x2="50%" y2="0%">',
            '      <stop offset="0%" stop-color="#991b1b" />',
            '      <stop offset="45%" stop-color="#ef4444" />',
            '      <stop offset="100%" stop-color="#f97316" />',
            "    </linearGradient>",
            '    <linearGradient id="flame-inner" x1="50%" y1="100%" x2="50%" y2="0%">',
            '      <stop offset="0%" stop-color="#f97316" />',
            '      <stop offset="55%" stop-color="#fbbf24" />',
            '      <stop offset="100%" stop-color="#fef08a" />',
            "    </linearGradient>",
            '    <linearGradient id="dwarven-iron" x1="0%" y1="0%" x2="0%" y2="100%">',
            '      <stop offset="0%" stop-color="#473e39" />',
            '      <stop offset="45%" stop-color="#292220" />',
            '      <stop offset="100%" stop-color="#14100f" />',
            "    </linearGradient>",
            '    <linearGradient id="slab-grad" x1="0%" y1="0%" x2="0%" y2="100%">',
            '      <stop offset="0%" stop-color="#1b0e09" stop-opacity="0.94" />',
            '      <stop offset="100%" stop-color="#0f0705" stop-opacity="0.96" />',
            "    </linearGradient>",
            '    <pattern id="khazad-lattice" width="64" height="64" '
            'patternUnits="userSpaceOnUse">',
            '      <path d="M 32 0 L 64 32 L 32 64 L 0 32 Z" fill="none" '
            'stroke="#ff6a00" stroke-width="0.9" stroke-opacity="0.14" />',
            '      <path d="M 16 16 L 32 4 L 48 16 M 16 48 L 32 60 L 48 48" fill="none" '
            'stroke="#d97706" stroke-width="0.8" stroke-opacity="0.13" />',
            '      <polygon points="32,28 36,32 32,36 28,32" fill="#fbbf24" fill-opacity="0.15" />',
            "    </pattern>",
            "  </defs>",
        ]
    )


def svg_canvas(width: int, height: int, body: str, sparks: int = 28, seed_offset: int = 0) -> str:
    """Wrap graphic body in self-contained Khazad-dûm volcanic basalt + coal-bed SVG."""
    spark_block = spark_field_svg(width, height, count=sparks, seed_offset=seed_offset)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">\n'
        f"{common_svg_defs()}\n"
        f'  <rect width="{width}" height="{height}" fill="url(#bg-basalt)" />\n'
        f'  <rect width="{width}" height="{height}" fill="url(#khazad-lattice)" />\n'
        f'  <rect width="{width}" height="{height}" fill="url(#hearth-aura)" />\n'
        f"{coal_bed_svg(width, height)}\n"
        f"{spark_block}\n"
        f"{body}\n"
        f"</svg>\n"
    )


def dwarven_forge_emblem_svg(cx: float, cy: float, scale: float = 1.0) -> str:
    """Iconic Khazad-dûm octagonal shield, coals, roaring flames, horned anvil & warhammer."""
    xf = f"translate({cx:.1f},{cy:.1f}) scale({scale:.3f}) translate(-256,-256)"
    o1 = oct_points(256, 256, 224)
    o2 = oct_points(256, 256, 198)
    o3 = oct_points(256, 256, 174)
    flame_out = (
        "M 134 388 C 114 320 148 258 176 218 C 174 260 198 268 206 232 "
        "C 218 182 244 150 256 118 C 274 156 294 188 304 234 C 318 264 "
        "338 252 338 214 C 368 256 396 320 378 388 Z"
    )
    flame_in = (
        "M 166 388 C 156 336 180 286 204 256 C 206 286 224 288 234 252 "
        "C 244 214 252 190 258 164 C 270 196 282 224 286 258 C 298 286 "
        "314 278 316 252 C 340 288 354 338 346 388 Z"
    )
    flame_core = "M 204 388 C 202 350 222 318 256 278 C 290 318 310 350 308 388 Z"
    anvil_d = (
        "M 92 268 L 176 250 L 176 242 L 368 242 L 368 256 L 408 256 "
        "L 396 286 L 350 286 L 314 314 L 314 352 L 354 382 L 354 398 "
        "L 166 398 L 166 382 L 206 352 L 206 314 L 168 292 Z"
    )
    coal_d = "M 118 390 Q 186 356 256 366 Q 326 356 394 390 L 362 426 L 150 426 Z"
    head_pts = "-66,-68 66,-68 78,-52 78,-18 66,-4 -66,-4 -78,-18 -78,-52"

    return "\n".join(
        [
            f'  <g transform="{xf}">',
            f'    <polygon points="{o1}" fill="#120805" '
            'stroke="url(#molten-gold)" stroke-width="15" />',
            f'    <polygon points="{o2}" fill="#190b07" stroke="#d97706" '
            'stroke-width="4" stroke-opacity="0.75" />',
            f'    <polygon points="{o3}" fill="#0d0503" stroke="#f97316" '
            'stroke-width="3" stroke-dasharray="22 10" />',
            '    <polygon points="256,42 266,52 256,62 246,52" fill="#ffd166" />',
            '    <polygon points="256,450 266,460 256,470 246,460" fill="#ffd166" />',
            '    <polygon points="42,256 52,246 62,256 52,266" fill="#ffd166" />',
            '    <polygon points="450,256 460,246 470,256 460,266" fill="#ffd166" />',
            '    <g stroke="#78350f" stroke-width="9" stroke-linecap="round" opacity="0.75">',
            '      <line x1="152" y1="378" x2="344" y2="150" />',
            '      <line x1="360" y1="378" x2="168" y2="150" />',
            "    </g>",
            f'    <path d="{coal_d}" fill="#991b1b" stroke="#ef4444" stroke-width="3" />',
            '    <polygon points="148,412 184,382 222,404 258,378 298,404 334,382 366,412" '
            'fill="#f97316" opacity="0.88" />',
            '    <polygon points="178,414 214,392 256,408 296,390 332,414" '
            'fill="#ffd166" opacity="0.85" />',
            f'    <path d="{flame_out}" fill="url(#flame-outer)" opacity="0.95" />',
            f'    <path d="{flame_in}" fill="url(#flame-inner)" opacity="0.95" />',
            f'    <path d="{flame_core}" fill="#fef08a" opacity="0.9" />',
            f'    <path d="{anvil_d}" fill="url(#dwarven-iron)" '
            'stroke="url(#molten-gold)" stroke-width="8" stroke-linejoin="miter" />',
            '    <line x1="176" y1="248" x2="366" y2="248" stroke="#fef08a" stroke-width="5" />',
            '    <polygon points="260,302 284,332 260,362 236,332" fill="none" '
            'stroke="#fbbf24" stroke-width="5" />',
            '    <polygon points="260,318 271,332 260,346 249,332" fill="#ff7b00" />',
            '    <g transform="translate(262, 232) rotate(-28)">',
            '      <rect x="-10" y="-138" width="20" height="118" rx="3" '
            'fill="#78350f" stroke="#fbbf24" stroke-width="4" />',
            f'      <polygon points="{head_pts}" fill="url(#dwarven-iron)" '
            'stroke="url(#molten-gold)" stroke-width="6" />',
            '      <polygon points="0,-54 18,-36 0,-18 -18,-36" fill="#fbbf24" />',
            "    </g>",
            '    <polygon points="256,214 264,232 284,236 266,244 256,262 246,244 '
            '228,236 248,232" fill="#fef08a" />',
            '    <g stroke="#ffd166" stroke-width="5" stroke-linecap="round">',
            '      <line x1="224" y1="220" x2="184" y2="188" />',
            '      <line x1="290" y1="218" x2="338" y2="182" />',
            '      <line x1="214" y1="238" x2="162" y2="226" />',
            '      <line x1="298" y1="238" x2="354" y2="224" />',
            "    </g>",
            '    <circle cx="172" cy="178" r="6" fill="#fef08a" />',
            '    <circle cx="348" cy="174" r="6" fill="#ffd166" />',
            '    <circle cx="148" cy="222" r="5" fill="#ff7b00" />',
            '    <circle cx="368" cy="220" r="5" fill="#ff7b00" />',
            "  </g>",
        ]
    )


def build_square_icon_svg() -> str:
    """512x512 square Khazad-dûm Dwarven Forge icon (zero tiny text for 32px–512px)."""
    body = (
        dwarven_corner_brackets_svg(18, 18, 476, 476, arm=42)
        + "\n"
        + dwarven_forge_emblem_svg(256, 256, scale=0.96)
    )
    return svg_canvas(512, 512, body, sparks=22, seed_offset=1)


def build_category_icon_svg(kind: str) -> str:
    """64x64 Khazad-dûm dwarven stage badges (all strokes >= 2.2px)."""
    oct_outer = oct_points(32, 32, 28)
    oct_inner = oct_points(32, 32, 24)
    glyphs: dict[str, str] = {
        "ingest": (
            '  <path d="M 16 20 L 38 14 L 35 32 C 34 38 23 39 20 33 Z" '
            'fill="#292220" stroke="#fbbf24" stroke-width="2.6" stroke-linejoin="round" />\n'
            '  <path d="M 37 20 C 44 24 45 35 43 48" fill="none" stroke="#ff7b00" '
            'stroke-width="4.4" stroke-linecap="round" />\n'
            '  <path d="M 37 20 C 43 24 44 35 43 48" fill="none" stroke="#fef08a" '
            'stroke-width="2.0" stroke-linecap="round" />\n'
            '  <circle cx="48" cy="34" r="2.2" fill="#ffd166" />\n'
            '  <circle cx="36" cy="46" r="2.4" fill="#ff5500" />'
        ),
        "template": (
            '  <polygon points="18,14 46,14 50,18 50,50 14,50 14,18" '
            'fill="#241712" stroke="#fbbf24" stroke-width="2.6" />\n'
            '  <polygon points="32,20 40,28 32,36 24,28" fill="none" '
            'stroke="#ffd166" stroke-width="2.4" />\n'
            '  <line x1="21" y1="43" x2="43" y2="43" stroke="#f97316" '
            'stroke-width="2.8" stroke-linecap="round" />'
        ),
        "sandbox": (
            '  <polygon points="32,14 46,20 46,36 32,50 18,36 18,20" '
            'fill="#26140f" stroke="#f97316" stroke-width="2.6" />\n'
            '  <line x1="20" y1="46" x2="42" y2="20" stroke="#ffd166" '
            'stroke-width="3.0" stroke-linecap="round" />\n'
            '  <polygon points="35,15 47,25 42,30 30,20" fill="#fbbf24" '
            'stroke="#fef08a" stroke-width="1.8" />'
        ),
        "verify": (
            '  <path d="M 14 38 L 24 35 L 46 35 L 44 41 L 38 44 L 41 50 L 23 50 L 26 44 Z" '
            'fill="#292220" stroke="#fbbf24" stroke-width="2.2" stroke-linejoin="round" />\n'
            '  <path d="M 19 25 L 28 33 L 46 15" fill="none" stroke="#10b981" '
            'stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round" />\n'
            '  <circle cx="18" cy="16" r="2.2" fill="#ffd166" />\n'
            '  <circle cx="48" cy="26" r="2.0" fill="#ff7b00" />'
        ),
        "govern": (
            '  <path d="M 16 48 L 16 28 C 16 17 48 17 48 28 L 48 48" '
            'fill="none" stroke="#fbbf24" stroke-width="2.8" />\n'
            '  <polygon points="22,34 27,24 32,31 37,24 42,34 40,42 24,42" '
            'fill="#291811" stroke="#ffd166" stroke-width="2.4" stroke-linejoin="round" />\n'
            '  <circle cx="32" cy="20" r="2.3" fill="#fef08a" />'
        ),
    }
    body = "\n".join(
        [
            svg_poly(oct_outer, "#140a06", "url(#molten-gold)", "3.2"),
            svg_poly(oct_inner, "#1b0d08", "#d97706", "1.4", 'stroke-opacity="0.7"'),
            glyphs[kind],
        ]
    )
    return svg_canvas(64, 64, body, sparks=6, seed_offset=len(kind))


def build_hero_logo_svg(stats: dict[str, Any]) -> str:
    """1200x380 Wide Khazad-dûm Dwarven Forge Hero Banner."""
    proto = stats["protocol"]
    tcount = stats["tool_count"]
    frame_pts = chamfer_rect_points(20, 20, 1160, 340, 22)
    plaques = [
        (356, 202, "5 GATES TEMPERED", "#10b981", "#071f17"),
        (572, 222, "100% TOOL BRANCH COV", "#fbbf24", "#241608"),
        (808, 186, f"{tcount} STATELESS TOOLS", "#f97316", "#261107"),
        (1008, 148, "SEP-2575 / 2567", "#ffd166", "#241809"),
    ]
    plaque_svg: list[str] = []
    for px, pw, label, stroke_col, fill_col in plaques:
        p_pts = chamfer_rect_points(px, 272, pw, 44, 8)
        cx = px + pw / 2
        plaque_svg.extend(
            [
                svg_poly(p_pts, fill_col, stroke_col, "1.8"),
                f'  <circle cx="{px + 10}" cy="294" r="2.2" fill="{stroke_col}" />',
                f'  <circle cx="{px + pw - 10}" cy="294" r="2.2" fill="{stroke_col}" />',
                svg_txt(cx, 299, label, stroke_col, MONO_STACK, 13, "700", anchor="middle"),
            ]
        )

    sub_str = f"Forged in the Deep Halls · OpenAPI 3.x -> Hardened FastMCP 4.x (MCP {proto})"
    lines = [
        svg_poly(frame_pts, "url(#slab-grad)", "#d97706", "2", 'stroke-opacity="0.85"'),
        dwarven_corner_brackets_svg(20, 20, 1160, 340, arm=42),
        dwarven_forge_emblem_svg(186, 190, scale=0.64),
        svg_poly("358,82 365,89 358,96 351,89", "#fbbf24"),
        svg_txt(
            376,
            94,
            f"KHAZAD-DÛM GREAT FORGE · MCP SPECIFICATION {proto}",
            "#fbbf24",
            MONO_STACK,
            14,
            "700",
            spacing="2.6",
        ),
        svg_txt(358, 160, "MCP SERVER FORGE", "#7c2d12", SERIF_STACK, 54, "800", spacing="2.2"),
        svg_txt(
            356,
            157,
            "MCP SERVER FORGE",
            "#f8fafc",
            SERIF_STACK,
            54,
            "800",
            spacing="2.2",
            stroke="#fbbf24",
            stroke_w="0.9",
        ),
        svg_txt(356, 202, sub_str, "#e2e8f0", SANS_STACK, 18.5, "600"),
        '  <line x1="356" y1="236" x2="1154" y2="236" '
        'stroke="url(#molten-channel)" stroke-width="2.4" />',
        svg_poly("755,229 764,236 755,243 746,236", "#fef08a"),
        *plaque_svg,
    ]
    return svg_canvas(1200, 380, "\n".join(lines), sparks=34, seed_offset=2)


def _great_hall_frame(title: str, subtitle: str, badge: str, badge_color: str = "#10b981") -> str:
    """Shared 1200x620 Khazad-dûm Great Forge chiseled stone slab & header."""
    slab = chamfer_rect_points(22, 22, 1156, 576, 22)
    badge_pts = chamfer_rect_points(936, 40, 214, 38, 8)
    badge_bg = "#072118" if badge_color == "#10b981" else "#261508"
    return "\n".join(
        [
            svg_poly(slab, "url(#slab-grad)", "#d97706", "2", 'stroke-opacity="0.82"'),
            dwarven_corner_brackets_svg(22, 22, 1156, 576, arm=40),
            '  <path d="M 52 64 L 68 60 L 96 60 L 92 68 L 84 72 L 88 80 '
            'L 64 80 L 68 72 Z" fill="#fbbf24" />',
            svg_txt(110, 66, title, "#f8fafc", SERIF_STACK, 22.5, "700", spacing="0.4"),
            svg_txt(110, 96, subtitle, "#cbd5e1", MONO_STACK, 12.8),
            svg_poly(badge_pts, badge_bg, badge_color, "1.8"),
            svg_txt(1043, 64, badge, badge_color, MONO_STACK, 12.5, "700", anchor="middle"),
            '  <line x1="52" y1="120" x2="1148" y2="120" '
            'stroke="url(#molten-channel)" stroke-width="2.0" stroke-opacity="0.75" />',
            svg_poly("600,114 607,120 600,126 593,120", "#ffd166"),
        ]
    )


def build_architecture_overview_svg(stats: dict[str, Any]) -> str:
    """1200x620 5-Stage Dwarven Pipeline (Smelt -> Mold -> Hammer -> Temper -> Seal)."""
    stages = [
        (
            "1 · SMELT",
            "OpenAPI Ingest",
            "forge/ingest_openapi.py",
            "$ref inline · <=15 tools",
            "#f97316",
            52,
        ),
        (
            "2 · MOLD",
            "Template Lock",
            "golden-template/",
            ":ro core · :rw src/tools",
            "#fbbf24",
            274,
        ),
        (
            "3 · HAMMER",
            "Tool Synthesis",
            "forge/codegen.py",
            "Pydantic 2020-12 + respx",
            "#ff7b00",
            496,
        ),
        (
            "4 · TEMPER",
            "5-Gate Harness",
            "scripts/validate_mcp.py",
            "--network=none · >=85%",
            "#10b981",
            718,
        ),
        (
            "5 · SEAL",
            "Governance",
            "forge-release-artifacts.json",
            "mcpServers + AppSec",
            "#ffd166",
            940,
        ),
    ]
    parts: list[str] = [
        _great_hall_frame(
            "MCP Server Forge — Smelt -> Mold -> Hammer -> Temper -> Seal",
            "5-Stage Khazad-dûm Pipeline & Stateless FastMCP 4.x Runtime (MCP 2026-07-28)",
            "5 STAGES PASS",
        )
    ]
    for idx in range(4):
        sx = 52 + idx * 222 + 206
        ex = sx + 16
        parts.append(
            f'  <line x1="{sx}" y1="236" x2="{ex}" y2="236" '
            'stroke="url(#molten-channel)" stroke-width="5" />'
        )
        parts.append(svg_poly(f"{ex - 2},229 {ex + 6},236 {ex - 2},243", "#fef08a"))

    for tag, name, path, detail, color, x in stages:
        pts = chamfer_rect_points(x, 146, 206, 182, 12)
        d_pts = f"{x + 18},168 {x + 24},162 {x + 30},168 {x + 24},174"
        parts.extend(
            [
                svg_poly(pts, "#160a06", color, "2.0"),
                svg_poly(d_pts, color),
                svg_txt(x + 36, 173, tag, color, MONO_STACK, 12.5, "700"),
                svg_txt(x + 16, 208, name, "#f8fafc", SERIF_STACK, 18, "700"),
                svg_txt(x + 16, 242, path, "#ffd166", MONO_STACK, 10.8),
                f'  <line x1="{x + 16}" y1="262" x2="{x + 190}" y2="262" '
                'stroke="#78350f" stroke-width="1.2" />',
                svg_txt(x + 16, 290, detail, "#e2e8f0", SANS_STACK, 13),
                svg_txt(x + 16, 314, "PASS · FORGED", "#10b981", MONO_STACK, 11, "700"),
            ]
        )

    vault_pts = chamfer_rect_points(52, 356, 1096, 212, 16)
    proto = stats["protocol"]
    tcount = stats["tool_count"]
    rt_hdr = (
        f"STATELESS FASTMCP 4.x GREAT HALL RUNTIME — MCP {proto} "
        "(src/server.py · src/auth.py · src/deps.py)"
    )
    parts.append(svg_poly(vault_pts, "#120805", "#fbbf24", "1.8"))
    parts.append(svg_txt(80, 392, rt_hdr, "#fbbf24", MONO_STACK, 13.5, "700"))

    chambers = [
        (
            78,
            330,
            "#f97316",
            "Lifespan Connection Hearth",
            "Depends(get_http_client) -> ApiClient",
            "No token passthrough · Env-bound Auth",
            "src/auth.py · src/deps.py",
        ),
        (
            434,
            332,
            "#10b981",
            "FileSystemProvider + Tools",
            f"src/tools/*.py ({tcount} tools discovered)",
            "JSON Schema 2020-12 outputSchema",
            "src/server.py · SEP-2575",
        ),
        (
            792,
            330,
            "#fbbf24",
            "ForgeResponseLimitingMiddleware",
            "max_response_bytes = 32,768",
            "Preserves outputSchema + bounds JSON",
            "Bounded Context Guard",
        ),
    ]
    for cx, cw, col, ctitle, l1, l2, l3 in chambers:
        c_pts = chamfer_rect_points(cx, 416, cw, 128, 10)
        parts.extend(
            [
                svg_poly(c_pts, "#1c0d08", col, "1.5"),
                svg_txt(cx + 18, 446, ctitle, "#f8fafc", SERIF_STACK, 15, "700"),
                svg_txt(cx + 18, 476, l1, "#ffd166", MONO_STACK, 12),
                svg_txt(cx + 18, 502, l2, "#cbd5e1", MONO_STACK, 12),
                svg_txt(cx + 18, 528, l3, "#10b981", MONO_STACK, 11.5, "700"),
            ]
        )

    return svg_canvas(1200, 620, "\n".join(parts), sparks=30, seed_offset=3)


def build_workflow_ingest_svg() -> str:
    """1200x620 Stage 1 OpenAPI 3.x Smelting Crucible & SSRF Guard."""
    p_left = chamfer_rect_points(52, 152, 332, 412, 14)
    p_mid = chamfer_rect_points(422, 152, 356, 412, 14)
    p_right = chamfer_rect_points(816, 152, 332, 412, 14)
    sub = (
        "python -m forge.ingest_openapi "
        "--spec spec/acme-incidents.openapi.yaml --name acme-incidents"
    )

    lines = [
        _great_hall_frame(
            "Stage 1 Smelting Crucible — OpenAPI 3.x & SSRF Guard",
            sub,
            "STAGE 1 · PASS",
        ),
        '  <line x1="384" y1="356" x2="422" y2="356" '
        'stroke="url(#molten-channel)" stroke-width="6" />',
        svg_poly("414,348 424,356 414,364", "#fef08a"),
        '  <line x1="778" y1="356" x2="816" y2="356" '
        'stroke="url(#molten-channel)" stroke-width="6" />',
        svg_poly("808,348 818,356 808,364", "#fef08a"),
        # Left panel
        svg_poly(p_left, "#160a06", "#f97316", "1.9"),
        svg_txt(76, 190, "RAW ORE · OpenAPI 3.1 YAML", "#f97316", MONO_STACK, 14, "700"),
        svg_txt(76, 228, "paths:", "#f8fafc", MONO_STACK, 13),
        svg_txt(76, 256, "  /incidents/{incident_id}:", "#ffd166", MONO_STACK, 13),
        svg_txt(76, 284, "    get: operationId: getIncident", "#e2e8f0", MONO_STACK, 12.5),
        svg_txt(76, 310, "    delete: operationId: deleteIncident", "#e2e8f0", MONO_STACK, 12.5),
        svg_txt(76, 350, "components.securitySchemes:", "#f8fafc", MONO_STACK, 13),
        svg_txt(76, 378, "  bearerAuth (HTTP Bearer)", "#ffd166", MONO_STACK, 13),
        svg_txt(76, 416, "$ref: '#/components/schemas/...'", "#fbbf24", MONO_STACK, 12.5),
        svg_txt(76, 456, "BLOCKED: http:// / file:// $ref", "#ef4444", MONO_STACK, 12),
        '  <path d="M 78 510 L 146 496 L 138 536 L 86 536 Z" '
        'fill="#291811" stroke="#fbbf24" stroke-width="2" />',
        svg_txt(162, 522, "CRUCIBLE CHARGE", "#ffd166", MONO_STACK, 12, "700"),
        # Center panel
        svg_poly(p_mid, "#190b07", "#fbbf24", "2.0"),
        svg_txt(446, 190, "SMELTING CRUCIBLE GUARDS", "#fbbf24", MONO_STACK, 14, "700"),
        svg_txt(
            446, 232, "1. Internal $ref Inlining (<=25 depth)", "#f8fafc", SERIF_STACK, 16, "700"
        ),
        svg_txt(
            446,
            256,
            "SSRF shield rejects http:// & file:// external $ref",
            "#cbd5e1",
            SANS_STACK,
            13,
        ),
        svg_txt(446, 304, "2. Context Budget Gate (<=15 tools)", "#f8fafc", SERIF_STACK, 16, "700"),
        svg_txt(
            446, 328, "Slices sprawling APIs cleanly via --tag-filter", "#cbd5e1", SANS_STACK, 13
        ),
        svg_txt(446, 376, "3. HTTP -> ToolAnnotations", "#f8fafc", SERIF_STACK, 16, "700"),
        svg_txt(
            446, 400, "GET=readOnly · DELETE=destructive · PUT=idemp", "#cbd5e1", SANS_STACK, 13
        ),
        svg_txt(446, 448, "4. Env-Bound Auth Extraction", "#f8fafc", SERIF_STACK, 16, "700"),
        svg_txt(446, 472, "bearer · api_key · basic · oauth2_cc", "#cbd5e1", SANS_STACK, 13),
        '  <rect x="446" y="502" width="308" height="36" rx="4" '
        'fill="#072118" stroke="#10b981" stroke-width="1.5" />',
        svg_txt(
            600,
            525,
            "PASS · ZERO SSRF / BOUNDED",
            "#10b981",
            MONO_STACK,
            12.5,
            "700",
            anchor="middle",
        ),
        # Right panel
        svg_poly(p_right, "#160a06", "#10b981", "1.9"),
        svg_txt(840, 190, "INGOT · forge-manifest.json", "#10b981", MONO_STACK, 14, "700"),
        svg_txt(840, 228, "{", "#f8fafc", MONO_STACK, 13),
        svg_txt(840, 256, '  "protocol_revision": "2026-07-28",', "#ffd166", MONO_STACK, 12.5),
        svg_txt(840, 284, '  "server_name": "acme-incidents",', "#ffd166", MONO_STACK, 12.5),
        svg_txt(840, 312, '  "auth": {"type": "bearer", ...},', "#e2e8f0", MONO_STACK, 12.5),
        svg_txt(840, 340, '  "upstream": {', "#e2e8f0", MONO_STACK, 12.5),
        svg_txt(840, 366, '    "max_response_bytes": 32768', "#fbbf24", MONO_STACK, 12.5),
        svg_txt(840, 392, "  },", "#e2e8f0", MONO_STACK, 12.5),
        svg_txt(840, 420, '  "tools": [ ... 5 tools ... ]', "#10b981", MONO_STACK, 12.5),
        svg_txt(840, 448, "}", "#f8fafc", MONO_STACK, 13),
        '  <path d="M 846 516 L 872 508 L 926 508 L 918 522 L 902 528 '
        'L 908 540 L 866 540 L 872 528 Z" fill="#fbbf24" />',
        svg_txt(942, 528, "PURE MITHRIL IR", "#ffd166", MONO_STACK, 12, "700"),
    ]
    return svg_canvas(1200, 620, "\n".join(lines), sparks=28, seed_offset=4)


def build_workflow_sandbox_svg() -> str:
    """1200x620 Stages 2–5 Runic :ro Lock vs :rw Anvil Overlay & Self-Healing Hammer Loop."""
    left_slab = chamfer_rect_points(52, 152, 520, 412, 14)
    ro_box = chamfer_rect_points(78, 212, 468, 152, 10)
    rw_box = chamfer_rect_points(78, 386, 468, 152, 10)
    right_slab = chamfer_rect_points(612, 152, 536, 412, 14)
    s1 = chamfer_rect_points(638, 214, 484, 88, 10)
    s2 = chamfer_rect_points(638, 322, 484, 88, 10)
    s3 = chamfer_rect_points(638, 430, 484, 110, 10)
    sub = "python -m forge.orchestrator --spec spec/acme-incidents.openapi.yaml --output-dir ./out"

    lines = [
        _great_hall_frame(
            "Stages 2–5 Runic :ro Lock & Self-Healing Hammer Loop",
            sub,
            "MAX_HEAL = 3 · PASS",
        ),
        '  <line x1="572" y1="358" x2="612" y2="358" '
        'stroke="url(#molten-channel)" stroke-width="6" />',
        svg_poly("604,350 614,358 604,366", "#fef08a"),
        svg_poly(left_slab, "#160a06", "#fbbf24", "1.9"),
        svg_txt(78, 190, "DWARVEN VAULT MOUNTS (DOCKER / LOCAL)", "#fbbf24", MONO_STACK, 14, "700"),
        svg_poly(ro_box, "#240b0b", "#ef4444", "1.8"),
        svg_txt(100, 242, "RUNIC :ro LOCK — IMMUTABLE BEDROCK", "#ef4444", MONO_STACK, 13, "700"),
        svg_txt(
            100,
            274,
            "pyproject.toml · Dockerfile · forge-manifest.json",
            "#f8fafc",
            MONO_STACK,
            12.5,
        ),
        svg_txt(100, 302, "src/server.py · src/auth.py · src/deps.py", "#f8fafc", MONO_STACK, 12.5),
        svg_txt(
            100,
            330,
            "tests/contract/test_forge_contract.py · validate_mcp.py",
            "#ffd166",
            MONO_STACK,
            12,
        ),
        svg_poly(rw_box, "#1f1208", "#10b981", "1.8"),
        svg_txt(
            100, 416, "GLOWING :rw ANVIL OVERLAY — AGENT-WRITABLE", "#10b981", MONO_STACK, 13, "700"
        ),
        svg_txt(
            100, 448, "src/tools/*.py        (stateless @tool modules)", "#f8fafc", MONO_STACK, 12.5
        ),
        svg_txt(
            100, 476, "tests/unit/*.py       (respx >=85% branch cov)", "#f8fafc", MONO_STACK, 12.5
        ),
        svg_txt(
            100, 504, "README.md             (setup & mcpServers docs)", "#ffd166", MONO_STACK, 12.5
        ),
        svg_poly(right_slab, "#160a06", "#f97316", "1.9"),
        svg_txt(
            638,
            190,
            "SELF-HEALING HAMMER LOOP (MAX_HEAL_ITERATIONS = 3)",
            "#f97316",
            MONO_STACK,
            14,
            "700",
        ),
        svg_poly(s1, "#211009", "#fbbf24", "1.6"),
        svg_txt(
            660,
            248,
            "Hammer Strike 1..3: Synthesize Tools & Unit Tests",
            "#f8fafc",
            SERIF_STACK,
            16,
            "700",
        ),
        svg_txt(
            660,
            278,
            "--cap-drop=ALL --security-opt=no-new-privileges (or --local)",
            "#ffd166",
            MONO_STACK,
            12,
        ),
        svg_poly(s2, "#211009", "#f97316", "1.6"),
        svg_txt(
            660,
            356,
            "Offline Quench Validation (--network=none)",
            "#f8fafc",
            SERIF_STACK,
            16,
            "700",
        ),
        svg_txt(
            660,
            386,
            "Feeds last 12,000 chars of diagnostics into retry hammer",
            "#cbd5e1",
            MONO_STACK,
            12,
        ),
        svg_poly(s3, "#0a2017", "#10b981", "1.8"),
        svg_txt(
            660,
            462,
            "Stage 5: Khazad-dûm Seal & Release Artifacts (PASS)",
            "#10b981",
            SERIF_STACK,
            16,
            "700",
        ),
        svg_txt(
            660,
            492,
            "Emits forge-release-artifacts.json + mcpServers snippet",
            "#f8fafc",
            MONO_STACK,
            12,
        ),
        svg_txt(
            660,
            518,
            "Flags destructiveHint=true for AppSec human signoff",
            "#fbbf24",
            MONO_STACK,
            12,
        ),
    ]
    return svg_canvas(1200, 620, "\n".join(lines), sparks=28, seed_offset=5)


def build_workflow_gates_svg() -> str:
    """1200x620 Stage 4 5-Gate Tempering Harness with Tempered Emerald PASS badges."""
    gates = [
        (
            "GATE 1",
            "Ruff + Bandit",
            "python -m ruff check src tests",
            "Blocks print() stdio corruption, S-bandit & lint defects",
            152,
        ),
        (
            "GATE 2",
            "Mypy --strict",
            "python -m mypy src",
            "Enforces Pydantic v2 typed BaseModel outputSchema",
            234,
        ),
        (
            "GATE 3",
            "AST & SEP-2577 Audit",
            "audit_tools_ast() -> src/tools/",
            "Blocks os/subprocess/open/eval, sample(), prompt-injection",
            316,
        ),
        (
            "GATE 4",
            "Pytest 100% Branch Cov",
            "pytest --cov=src/tools --cov-branch",
            "Verifies 2020-12 schemas, x-mcp-header & 100% branch cov",
            398,
        ),
        (
            "GATE 5",
            "Subprocess STDIO server/discover",
            "PythonStdioTransport -> server/discover",
            "Asserts protocol_version == '2026-07-28' & frame hygiene",
            480,
        ),
    ]
    rows: list[str] = [
        _great_hall_frame(
            "Stage 4 Tempering Harness — 5-Gate MCP 2026-07-28 Verification",
            "python scripts/validate_mcp.py — deterministic zero-network compliance tempering",
            "ALL 5 GATES PASS",
        ),
        '  <line x1="119" y1="152" x2="119" y2="550" '
        'stroke="url(#molten-gold)" stroke-width="4" />',
    ]
    for code, title, cmd, desc, y in gates:
        row_pts = chamfer_rect_points(52, y, 1096, 68, 10)
        tag_pts = chamfer_rect_points(70, y + 16, 98, 36, 6)
        pass_pts = chamfer_rect_points(1054, y + 17, 76, 34, 6)
        rows.extend(
            [
                svg_poly(row_pts, "#170b07", "#fbbf24", "1.6"),
                svg_poly(tag_pts, "#281309", "#f97316", "1.5"),
                svg_txt(119, y + 39, code, "#ffd166", MONO_STACK, 13, "700", anchor="middle"),
                svg_txt(188, y + 30, title, "#f8fafc", SERIF_STACK, 17, "700"),
                svg_txt(188, y + 53, desc, "#cbd5e1", SANS_STACK, 13),
                svg_txt(1036, y + 39, cmd, "#ffd166", MONO_STACK, 12, anchor="end"),
                svg_poly(pass_pts, "#07241a", "#10b981", "1.6"),
                svg_txt(1092, y + 39, "PASS", "#10b981", MONO_STACK, 12.5, "700", anchor="middle"),
            ]
        )

    return svg_canvas(1200, 620, "\n".join(rows), sparks=30, seed_offset=6)


# ---------------------------------------------------------------------------
# High-Craft Khazad-dûm Dwarven Forge Pillow PNG Renderer
# ---------------------------------------------------------------------------


def _load_pil_font(kind: str, size: int) -> Any:
    """Load crisp system TrueType font on macOS/Linux with safe Pillow fallback."""
    from PIL import ImageFont

    candidates_map = {
        "serif": [
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        ],
        "sans": [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "mono": [
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/SFNSMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ],
    }
    for path_str in candidates_map.get(kind, []):
        if Path(path_str).exists():
            try:
                return ImageFont.truetype(path_str, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _draw_centered_text(
    draw: Any, cx: float, cy: float, text: str, font: Any, fill: tuple[int, ...]
) -> None:
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text, font=font, fill=fill)


def _draw_right_text(
    draw: Any, rx: float, y: float, text: str, font: Any, fill: tuple[int, ...]
) -> None:
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    draw.text((rx - tw - bbox[0], y), text, font=font, fill=fill)


def _create_khazad_canvas(width: int, height: int, seed_offset: int = 0) -> Any:
    """Create volcanic basalt canvas with dwarven diamond lattice, glowing coal bed & sparks."""
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGBA", (width, height), (*RGB_BASALT_TOP, 255))
    bg_draw = ImageDraw.Draw(img)

    for y in range(height):
        t = y / max(1, height - 1)
        if t < 0.55:
            u = t / 0.55
            r = int(RGB_BASALT_TOP[0] * (1 - u) + RGB_BASALT_MID[0] * u)
            g = int(RGB_BASALT_TOP[1] * (1 - u) + RGB_BASALT_MID[1] * u)
            b = int(RGB_BASALT_TOP[2] * (1 - u) + RGB_BASALT_MID[2] * u)
        else:
            u = (t - 0.55) / 0.45
            r = int(RGB_BASALT_MID[0] * (1 - u) + RGB_BASALT_BOT[0] * u)
            g = int(RGB_BASALT_MID[1] * (1 - u) + RGB_BASALT_BOT[1] * u)
            b = int(RGB_BASALT_MID[2] * (1 - u) + RGB_BASALT_BOT[2] * u)
        if t > 0.68:
            coal_u = ((t - 0.68) / 0.32) ** 1.7
            r = min(255, int(r + 135 * coal_u))
            g = min(255, int(g + 34 * coal_u))
            b = min(255, int(b + 10 * coal_u))
        bg_draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    lattice = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(lattice)
    cell = max(32, min(64, width // 14))
    half = cell // 2
    lw = max(1, width // 600)
    for gy in range(0, height + cell, cell):
        for gx in range(0, width + cell, cell):
            pts = [
                (gx + half, gy),
                (gx + cell, gy + half),
                (gx + half, gy + cell),
                (gx, gy + half),
            ]
            ldraw.polygon(pts, outline=(255, 106, 0, 38), width=lw)
            d = max(2, cell // 14)
            ldraw.polygon(
                [
                    (gx + half, gy + half - d),
                    (gx + half + d, gy + half),
                    (gx + half, gy + half + d),
                    (gx + half - d, gy + half),
                ],
                fill=(251, 191, 36, 36),
            )
    img = Image.alpha_composite(img, lattice)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx_hearth = width // 2 if width == height else int(width * 0.32)
    rx_aura = int(width * 0.36)
    gdraw.ellipse(
        [cx_hearth - rx_aura, int(height * 0.25), cx_hearth + rx_aura, int(height * 0.95)],
        fill=(255, 85, 0, 48),
    )
    step = max(32, width // 16)
    coal_cols = [
        (153, 27, 27, 150),
        (234, 88, 12, 145),
        (249, 115, 22, 155),
        (251, 191, 36, 130),
    ]
    for idx, x in enumerate(range(8, width - 12, step)):
        w = step - 4
        peak = height - int(height * 0.05) - (idx % 3) * max(4, height // 65)
        gdraw.polygon(
            [
                (x, height),
                (x + w // 3, peak),
                (x + (2 * w) // 3, peak + 4),
                (x + w, height),
            ],
            fill=coal_cols[idx % len(coal_cols)],
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(4, min(width, height) // 36)))
    img = Image.alpha_composite(img, glow)

    sdraw = ImageDraw.Draw(img)
    spark_cols = [
        (255, 209, 102, 220),
        (255, 123, 0, 210),
        (255, 59, 0, 195),
        (254, 240, 138, 230),
    ]
    phi = 0.61803398875
    count = 26 if width >= 512 else 12
    for idx in range(count):
        n = idx + 1 + seed_offset * 7
        fx = (n * phi) % 1.0
        fy = ((n * phi * 1.73205) % 1.0) ** 0.78
        sx = 18 + fx * (width - 36)
        sy = height - 10 - fy * (height * 0.80)
        sr = max(1.5, (1.4 + (idx % 3) * 1.0) * (width / 600.0))
        sdraw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=spark_cols[idx % 4])
    return img


def _draw_khazad_brackets_pil(
    draw: Any, x: float, y: float, w: float, h: float, arm: float, lw: int
) -> None:
    cham = arm * 0.42
    x2, y2 = x + w, y + h
    segs = [
        [(x, y + arm), (x, y + cham), (x + cham, y), (x + arm, y)],
        [(x2 - arm, y), (x2 - cham, y), (x2, y + cham), (x2, y + arm)],
        [(x, y2 - arm), (x, y2 - cham), (x + cham, y2), (x + arm, y2)],
        [(x2 - arm, y2), (x2 - cham, y2), (x2, y2 - cham), (x2, y2 - arm)],
    ]
    for pts in segs:
        draw.line(pts, fill=(*RGB_MOLTEN_GOLD, 255), width=lw)


def _draw_dwarven_emblem_pil(img: Any, cx: float, cy: float, scale: float) -> None:
    """Draw octagonal Khazad-dûm shield, coals, roaring flames, horned anvil & warhammer."""
    from PIL import Image, ImageDraw, ImageFilter

    def pt(px: float, py: float) -> tuple[float, float]:
        return (cx + (px - 256.0) * scale, cy + (py - 256.0) * scale)

    def pts_list(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [pt(px, py) for px, py in coords]

    draw = ImageDraw.Draw(img)
    sw_outer = max(3, int(14 * scale))
    sw_mid = max(2, int(4 * scale))

    draw.polygon(
        oct_coords(cx, cy, 224 * scale),
        fill=(18, 8, 5, 255),
        outline=(*RGB_MOLTEN_GOLD, 255),
        width=sw_outer,
    )
    draw.polygon(
        oct_coords(cx, cy, 196 * scale),
        fill=(25, 11, 7, 255),
        outline=(*RGB_FORGE_ORANGE, 200),
        width=sw_mid,
    )
    draw.polygon(
        oct_coords(cx, cy, 172 * scale),
        fill=(13, 5, 3, 255),
        outline=(217, 119, 6, 180),
        width=max(1, int(3 * scale)),
    )

    for sx, sy in [(256, 52), (256, 460), (52, 256), (460, 256)]:
        d = 10 * scale
        scx, scy = pt(sx, sy)
        draw.polygon(
            [(scx, scy - d), (scx + d, scy), (scx, scy + d), (scx - d, scy)],
            fill=(*RGB_BRIGHT_GOLD, 255),
        )

    tong_w = max(2, int(8 * scale))
    draw.line([pt(152, 378), pt(344, 150)], fill=(120, 53, 15, 210), width=tong_w)
    draw.line([pt(360, 378), pt(168, 150)], fill=(120, 53, 15, 210), width=tong_w)

    bloom = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bloom)
    bdraw.ellipse([pt(126, 140), pt(386, 420)], fill=(255, 95, 0, 95))
    bloom = bloom.filter(ImageFilter.GaussianBlur(radius=max(3, int(18 * scale))))
    img.alpha_composite(bloom)
    draw = ImageDraw.Draw(img)

    outer_flame = [
        (136, 388),
        (124, 314),
        (168, 224),
        (194, 260),
        (222, 192),
        (256, 120),
        (290, 194),
        (316, 258),
        (344, 220),
        (386, 314),
        (376, 388),
    ]
    mid_flame = [
        (168, 388),
        (162, 326),
        (198, 258),
        (222, 282),
        (256, 166),
        (290, 280),
        (316, 256),
        (348, 326),
        (344, 388),
    ]
    core_flame = [(206, 388), (214, 332), (256, 274), (298, 332), (306, 388)]
    draw.polygon(pts_list(outer_flame), fill=(*RGB_EMBER_CRIMSON, 242))
    draw.polygon(pts_list(mid_flame), fill=(*RGB_FORGE_ORANGE, 248))
    draw.polygon(pts_list(core_flame), fill=(*RGB_WHITE_GOLD, 245))

    coal_poly = [
        (124, 392),
        (176, 368),
        (224, 382),
        (256, 366),
        (292, 382),
        (338, 368),
        (388, 392),
        (358, 426),
        (154, 426),
    ]
    draw.polygon(
        pts_list(coal_poly),
        fill=(*RGB_COAL_DARK, 255),
        outline=(*RGB_FORGE_ORANGE, 255),
        width=max(2, int(3 * scale)),
    )
    coal_bright = [(164, 414), (206, 388), (256, 404), (306, 388), (348, 414)]
    draw.polygon(pts_list(coal_bright), fill=(*RGB_MOLTEN_GOLD, 225))

    anvil_pts = [
        (92, 268),
        (176, 250),
        (176, 242),
        (368, 242),
        (368, 256),
        (408, 256),
        (396, 286),
        (350, 286),
        (314, 314),
        (314, 352),
        (354, 382),
        (354, 398),
        (166, 398),
        (166, 382),
        (206, 352),
        (206, 314),
        (168, 292),
    ]
    draw.polygon(
        pts_list(anvil_pts),
        fill=(*RGB_IRON_DARK, 255),
        outline=(*RGB_MOLTEN_GOLD, 255),
        width=max(2, int(7 * scale)),
    )
    draw.line(
        [pt(178, 248), pt(366, 248)],
        fill=(*RGB_WHITE_GOLD, 255),
        width=max(2, int(4 * scale)),
    )
    draw.polygon(
        pts_list([(260, 304), (282, 332), (260, 360), (238, 332)]),
        fill=(*RGB_FORGE_ORANGE, 255),
        outline=(*RGB_BRIGHT_GOLD, 255),
        width=max(1, int(4 * scale)),
    )

    ang = math.radians(-28.0)
    cos_a, sin_a = math.cos(ang), math.sin(ang)

    def hpt(lx: float, ly: float) -> tuple[float, float]:
        rx = 262.0 + lx * cos_a - ly * sin_a
        ry = 232.0 + lx * sin_a + ly * cos_a
        return pt(rx, ry)

    haft = [hpt(-10, -138), hpt(10, -138), hpt(10, -20), hpt(-10, -20)]
    draw.polygon(
        haft,
        fill=(120, 53, 15, 255),
        outline=(*RGB_MOLTEN_GOLD, 255),
        width=max(1, int(3 * scale)),
    )
    head = [
        hpt(-66, -68),
        hpt(66, -68),
        hpt(78, -52),
        hpt(78, -18),
        hpt(66, -4),
        hpt(-66, -4),
        hpt(-78, -18),
        hpt(-78, -52),
    ]
    draw.polygon(
        head,
        fill=(*RGB_IRON_LIGHT, 255),
        outline=(*RGB_MOLTEN_GOLD, 255),
        width=max(2, int(5 * scale)),
    )
    draw.polygon(
        [hpt(0, -54), hpt(18, -36), hpt(0, -18), hpt(-18, -36)],
        fill=(*RGB_MOLTEN_GOLD, 255),
    )

    spark_w = max(2, int(4 * scale))
    for p_start, p_end in [
        ((224, 220), (180, 184)),
        ((290, 218), (342, 180)),
        ((214, 238), (158, 224)),
        ((298, 238), (358, 222)),
    ]:
        draw.line([pt(*p_start), pt(*p_end)], fill=(*RGB_WHITE_GOLD, 255), width=spark_w)
    scx, scy = pt(256, 238)
    sr = max(3, int(14 * scale))
    draw.polygon(
        [
            (scx, scy - sr),
            (scx + sr * 0.4, scy - sr * 0.3),
            (scx + sr, scy),
            (scx + sr * 0.4, scy + sr * 0.3),
            (scx, scy + sr),
            (scx - sr * 0.4, scy + sr * 0.3),
            (scx - sr, scy),
            (scx - sr * 0.4, scy - sr * 0.3),
        ],
        fill=(*RGB_WHITE_GOLD, 255),
    )


def _render_square_icon_png(png_path: Path) -> None:
    """Render 2x supersampled 512x512 Khazad-dûm square icon PNG."""
    from PIL import Image, ImageDraw

    ss = 2
    w, h = 512 * ss, 512 * ss
    img = _create_khazad_canvas(w, h, seed_offset=1)
    draw = ImageDraw.Draw(img)
    _draw_khazad_brackets_pil(draw, 18 * ss, 18 * ss, 476 * ss, 476 * ss, 42 * ss, 3 * ss)
    _draw_dwarven_emblem_pil(img, 256 * ss, 256 * ss, scale=0.96 * ss)
    out = img.resize((512, 512), Image.Resampling.LANCZOS).convert("RGB")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(png_path, format="PNG", optimize=True)


def _render_category_icon_png(png_path: Path, kind: str) -> None:
    """Render 2x supersampled 256x256 Khazad-dûm category badge PNG."""
    from PIL import Image, ImageDraw

    ss = 2
    size = 256 * ss
    scale = size / 64.0
    img = _create_khazad_canvas(size, size, seed_offset=len(kind))
    draw = ImageDraw.Draw(img)

    def sc(px: float, py: float) -> tuple[float, float]:
        return (px * scale, py * scale)

    draw.polygon(
        oct_coords(32 * scale, 32 * scale, 28 * scale),
        fill=(20, 10, 6, 255),
        outline=(*RGB_MOLTEN_GOLD, 255),
        width=int(3.2 * scale),
    )
    draw.polygon(
        oct_coords(32 * scale, 32 * scale, 24 * scale),
        fill=(27, 13, 8, 255),
        outline=(*RGB_FORGE_ORANGE, 185),
        width=int(1.4 * scale),
    )

    lw = int(2.8 * scale)
    if kind == "ingest":
        draw.polygon(
            [sc(16, 20), sc(38, 14), sc(35, 33), sc(20, 34)],
            fill=(*RGB_IRON_LIGHT, 255),
            outline=(*RGB_MOLTEN_GOLD, 255),
            width=lw,
        )
        # Seamless molten stream polygon + white-gold core
        draw.polygon(
            [sc(36, 18), sc(40, 18), sc(46, 32), sc(46, 49), sc(40, 49), sc(40, 32)],
            fill=(*RGB_FORGE_ORANGE, 255),
        )
        draw.polygon(
            [sc(37.2, 19), sc(39.2, 19), sc(44.2, 32), sc(44.2, 48), sc(41.8, 48), sc(41.8, 32)],
            fill=(*RGB_WHITE_GOLD, 255),
        )
    elif kind == "template":
        draw.polygon(
            [sc(18, 14), sc(46, 14), sc(50, 18), sc(50, 50), sc(14, 50), sc(14, 18)],
            fill=(36, 23, 18, 255),
            outline=(*RGB_MOLTEN_GOLD, 255),
            width=lw,
        )
        draw.polygon(
            [sc(32, 20), sc(40, 28), sc(32, 36), sc(24, 28)],
            outline=(*RGB_BRIGHT_GOLD, 255),
            width=lw,
        )
        draw.line([sc(21, 43), sc(43, 43)], fill=(*RGB_FORGE_ORANGE, 255), width=lw)
    elif kind == "sandbox":
        draw.polygon(
            [sc(32, 14), sc(46, 20), sc(46, 36), sc(32, 50), sc(18, 36), sc(18, 20)],
            fill=(38, 20, 15, 255),
            outline=(*RGB_FORGE_ORANGE, 255),
            width=lw,
        )
        draw.line([sc(20, 46), sc(42, 20)], fill=(*RGB_BRIGHT_GOLD, 255), width=int(3.2 * scale))
        draw.polygon(
            [sc(35, 15), sc(47, 25), sc(42, 30), sc(30, 20)],
            fill=(*RGB_MOLTEN_GOLD, 255),
            outline=(*RGB_WHITE_GOLD, 255),
            width=int(1.6 * scale),
        )
    elif kind == "verify":
        draw.polygon(
            [
                sc(14, 38),
                sc(24, 35),
                sc(46, 35),
                sc(44, 41),
                sc(38, 44),
                sc(41, 50),
                sc(23, 50),
                sc(26, 44),
            ],
            fill=(*RGB_IRON_DARK, 255),
            outline=(*RGB_MOLTEN_GOLD, 255),
            width=int(2.2 * scale),
        )
        # Seamless chiseled emerald checkmark polygon
        draw.polygon(
            [
                sc(17.5, 24.5),
                sc(20.8, 21.2),
                sc(28.0, 28.4),
                sc(44.5, 11.8),
                sc(48.0, 15.3),
                sc(28.0, 35.4),
            ],
            fill=(*RGB_EMERALD, 255),
        )
    else:
        draw.arc(
            [int(16 * scale), int(16 * scale), int(48 * scale), int(42 * scale)],
            start=180,
            end=0,
            fill=(*RGB_MOLTEN_GOLD, 255),
            width=lw,
        )
        draw.line([sc(16, 29), sc(16, 48)], fill=(*RGB_MOLTEN_GOLD, 255), width=lw)
        draw.line([sc(48, 29), sc(48, 48)], fill=(*RGB_MOLTEN_GOLD, 255), width=lw)
        draw.polygon(
            [
                sc(22, 34),
                sc(27, 24),
                sc(32, 31),
                sc(37, 24),
                sc(42, 34),
                sc(40, 43),
                sc(24, 43),
            ],
            fill=(41, 24, 17, 255),
            outline=(*RGB_BRIGHT_GOLD, 255),
            width=int(2.2 * scale),
        )

    out = img.resize((256, 256), Image.Resampling.LANCZOS).convert("RGB")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(png_path, format="PNG", optimize=True)


def _render_hero_banner_png(png_path: Path, stats: dict[str, Any]) -> None:
    """Render 1200x380 Wide Khazad-dûm Hero Banner PNG."""
    from PIL import ImageDraw

    w, h = 1200, 380
    img = _create_khazad_canvas(w, h, seed_offset=2)
    draw = ImageDraw.Draw(img)

    draw.polygon(
        chamfer_rect_coords(20, 20, 1160, 340, 22),
        fill=(*RGB_SLAB, 238),
        outline=(217, 119, 6, 220),
        width=2,
    )
    _draw_khazad_brackets_pil(draw, 20, 20, 1160, 340, 42, 3)
    _draw_dwarven_emblem_pil(img, 186, 190, scale=0.64)
    draw = ImageDraw.Draw(img)

    f_over = _load_pil_font("mono", 14)
    f_title = _load_pil_font("serif", 50)
    f_sub = _load_pil_font("sans", 18)
    f_pill = _load_pil_font("mono", 13)

    proto = stats["protocol"]
    tcount = stats["tool_count"]

    draw.polygon([(358, 82), (365, 89), (358, 96), (351, 89)], fill=(*RGB_MOLTEN_GOLD, 255))
    draw.text(
        (374, 80),
        f"KHAZAD-DÛM GREAT FORGE · MCP SPECIFICATION {proto}",
        font=f_over,
        fill=(*RGB_MOLTEN_GOLD, 255),
    )
    draw.text((358, 112), "MCP SERVER FORGE", font=f_title, fill=(124, 45, 18, 255))
    draw.text((355, 109), "MCP SERVER FORGE", font=f_title, fill=(*RGB_MITHRIL, 255))
    draw.text(
        (356, 182),
        f"Forged in the Deep Halls · OpenAPI 3.x -> Hardened FastMCP 4.x (MCP {proto})",
        font=f_sub,
        fill=(*RGB_STONE_TEXT, 255),
    )

    draw.line([(356, 234), (1154, 234)], fill=(*RGB_MOLTEN_GOLD, 220), width=3)
    draw.polygon([(755, 227), (763, 234), (755, 241), (747, 234)], fill=(*RGB_WHITE_GOLD, 255))

    plaques = [
        (356, 202, "5 GATES TEMPERED", RGB_EMERALD, (7, 31, 23, 245)),
        (572, 222, "100% TOOL BRANCH COV", RGB_MOLTEN_GOLD, (36, 22, 8, 245)),
        (808, 186, f"{tcount} STATELESS TOOLS", RGB_FORGE_ORANGE, (38, 17, 7, 245)),
        (1008, 148, "SEP-2575 / 2567", RGB_BRIGHT_GOLD, (36, 24, 9, 245)),
    ]
    for px, pw, label, stroke_rgb, bg_rgba in plaques:
        draw.polygon(
            chamfer_rect_coords(px, 270, pw, 44, 8),
            fill=bg_rgba,
            outline=(*stroke_rgb, 255),
            width=2,
        )
        _draw_centered_text(draw, px + pw / 2, 292, label, f_pill, (*stroke_rgb, 255))

    png_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(png_path, format="PNG", optimize=True)


def _draw_example_header_pil(draw: Any, title: str, subtitle: str, badge: str) -> None:
    draw.polygon(
        chamfer_rect_coords(22, 22, 1156, 576, 22),
        fill=(*RGB_SLAB, 238),
        outline=(217, 119, 6, 215),
        width=2,
    )
    _draw_khazad_brackets_pil(draw, 22, 22, 1156, 576, 40, 3)

    draw.polygon(
        [(52, 64), (68, 60), (96, 60), (92, 68), (84, 72), (88, 80), (64, 80), (68, 72)],
        fill=(*RGB_MOLTEN_GOLD, 255),
    )
    f_h1 = _load_pil_font("serif", 21)
    f_sub = _load_pil_font("mono", 12)
    f_bdg = _load_pil_font("mono", 12)
    draw.text((110, 46), title, font=f_h1, fill=(*RGB_MITHRIL, 255))
    draw.text((110, 86), subtitle, font=f_sub, fill=(*RGB_STONE_TEXT, 255))

    draw.polygon(
        chamfer_rect_coords(936, 40, 214, 38, 8),
        fill=(7, 33, 24, 245),
        outline=(*RGB_EMERALD, 255),
        width=2,
    )
    _draw_centered_text(draw, 1043, 59, badge, f_bdg, (*RGB_EMERALD, 255))
    draw.line([(52, 120), (1148, 120)], fill=(*RGB_MOLTEN_GOLD, 195), width=2)


def _render_example_png(png_path: Path, slug: str, stats: dict[str, Any]) -> None:
    """Render tailored 1200x620 Khazad-dûm Dwarven Forge architecture & workflow PNGs."""
    from PIL import ImageDraw

    w, h = 1200, 620
    img = _create_khazad_canvas(w, h, seed_offset=len(slug))
    draw = ImageDraw.Draw(img)

    f_tag = _load_pil_font("mono", 12)
    f_card = _load_pil_font("serif", 15)
    f_mono = _load_pil_font("mono", 12)
    f_body = _load_pil_font("sans", 13)

    if slug == "architecture-overview":
        _draw_example_header_pil(
            draw,
            "MCP Server Forge — Smelt -> Mold -> Hammer -> Temper -> Seal",
            "5-Stage Khazad-dûm Pipeline & Stateless FastMCP 4.x Runtime (MCP 2026-07-28)",
            "5 STAGES PASS",
        )
        stages = [
            (
                "1 · SMELT",
                "OpenAPI Ingest",
                "forge/ingest_openapi.py",
                "$ref inline · <=15 tools",
                RGB_FORGE_ORANGE,
                52,
            ),
            (
                "2 · MOLD",
                "Template Lock",
                "golden-template/",
                ":ro core · :rw src/tools",
                RGB_MOLTEN_GOLD,
                274,
            ),
            (
                "3 · HAMMER",
                "Tool Synthesis",
                "forge/codegen.py",
                "Pydantic 2020-12 + respx",
                (255, 123, 0),
                496,
            ),
            (
                "4 · TEMPER",
                "5-Gate Harness",
                "scripts/validate_mcp.py",
                "--network=none · >=85%",
                RGB_EMERALD,
                718,
            ),
            (
                "5 · SEAL",
                "Governance",
                "forge-release-artifacts",
                "mcpServers + AppSec",
                RGB_BRIGHT_GOLD,
                940,
            ),
        ]
        for idx in range(4):
            sx = 52 + idx * 222 + 206
            draw.line([(sx, 236), (sx + 16, 236)], fill=(*RGB_MOLTEN_GOLD, 255), width=5)
        for tag, name, path, detail, col, x in stages:
            draw.polygon(
                chamfer_rect_coords(x, 146, 206, 182, 12),
                fill=(*RGB_SLAB_INNER, 245),
                outline=(*col, 255),
                width=2,
            )
            draw.text((x + 16, 160), tag, font=f_tag, fill=(*col, 255))
            draw.text((x + 16, 192), name, font=f_card, fill=(*RGB_MITHRIL, 255))
            draw.text((x + 16, 228), path, font=f_mono, fill=(*RGB_BRIGHT_GOLD, 255))
            draw.text((x + 16, 268), detail, font=f_body, fill=(*RGB_STONE_TEXT, 255))
            draw.text((x + 16, 298), "PASS · FORGED", font=f_tag, fill=(*RGB_EMERALD, 255))

        draw.polygon(
            chamfer_rect_coords(52, 356, 1096, 212, 16),
            fill=(18, 8, 5, 245),
            outline=(*RGB_MOLTEN_GOLD, 220),
            width=2,
        )
        rt_title = (
            f"STATELESS FASTMCP 4.x RUNTIME — MCP {stats['protocol']} "
            "(src/server.py · src/auth.py · src/deps.py)"
        )
        draw.text((80, 376), rt_title, font=f_mono, fill=(*RGB_MOLTEN_GOLD, 255))
        chambers = [
            (
                78,
                "Lifespan Connection Hearth",
                "Depends(get_http_client) -> ApiClient",
                "No token passthrough · Env-bound Auth",
                RGB_FORGE_ORANGE,
            ),
            (
                434,
                "FileSystemProvider + Tools",
                f"src/tools/*.py ({stats['tool_count']} tools discovered)",
                "JSON Schema 2020-12 outputSchema",
                RGB_EMERALD,
            ),
            (
                792,
                "ForgeResponseLimitingMiddleware",
                "max_response_bytes = 32,768",
                "Preserves outputSchema + bounds JSON",
                RGB_MOLTEN_GOLD,
            ),
        ]
        for cx, ctitle, l1, l2, col in chambers:
            draw.polygon(
                chamfer_rect_coords(cx, 414, 330, 130, 10),
                fill=(*RGB_SLAB_INNER, 245),
                outline=(*col, 235),
                width=2,
            )
            draw.text((cx + 18, 434), ctitle, font=f_card, fill=(*RGB_MITHRIL, 255))
            draw.text((cx + 18, 468), l1, font=f_mono, fill=(*RGB_BRIGHT_GOLD, 255))
            draw.text((cx + 18, 498), l2, font=f_mono, fill=(*RGB_STONE_TEXT, 255))

    elif slug == "workflow-openapi-ingest":
        _draw_example_header_pil(
            draw,
            "Stage 1 Smelting Crucible — OpenAPI 3.x & SSRF Guard",
            "python -m forge.ingest_openapi --spec spec/acme-incidents.openapi.yaml "
            "--name acme-incidents",
            "STAGE 1 · PASS",
        )
        cols = [
            (
                52,
                332,
                "RAW ORE · OpenAPI 3.1 YAML",
                RGB_FORGE_ORANGE,
                [
                    "paths:",
                    "  /incidents/{incident_id}:",
                    "    get: getIncident",
                    "    delete: deleteIncident",
                    "securitySchemes: bearerAuth",
                    "$ref: '#/components/schemas/...'",
                    "BLOCKED: http:// & file:// $ref",
                ],
            ),
            (
                422,
                356,
                "SMELTING CRUCIBLE GUARDS",
                RGB_MOLTEN_GOLD,
                [
                    "1. Internal $ref Inlining (<=25 depth)",
                    "   Rejects external SSRF URIs",
                    "2. Context Budget Gate (<=15 tools)",
                    "   Slices large specs via --tag-filter",
                    "3. HTTP -> ToolAnnotations Mapping",
                    "   GET=readOnly · DELETE=destructive",
                    "4. Env-Bound Auth Extraction",
                ],
            ),
            (
                816,
                332,
                "INGOT · forge-manifest.json",
                RGB_EMERALD,
                [
                    "{",
                    '  "protocol_revision": "2026-07-28",',
                    '  "server_name": "acme-incidents",',
                    '  "auth": {"type": "bearer"},',
                    '  "max_response_bytes": 32768,',
                    '  "tools": [ 5 stateless tools ]',
                    "}",
                ],
            ),
        ]
        draw.line([(384, 356), (422, 356)], fill=(*RGB_MOLTEN_GOLD, 255), width=6)
        draw.line([(778, 356), (816, 356)], fill=(*RGB_MOLTEN_GOLD, 255), width=6)
        for px, pw, hdr, col, lines in cols:
            draw.polygon(
                chamfer_rect_coords(px, 152, pw, 412, 14),
                fill=(*RGB_SLAB_INNER, 245),
                outline=(*col, 255),
                width=2,
            )
            draw.text((px + 22, 174), hdr, font=f_mono, fill=(*col, 255))
            for idx, ln in enumerate(lines):
                fill_c = (*RGB_MITHRIL, 255) if idx % 2 == 0 else (*RGB_STONE_TEXT, 255)
                draw.text((px + 22, 222 + idx * 42), ln, font=f_mono, fill=fill_c)

    elif slug == "workflow-self-healing-sandbox":
        _draw_example_header_pil(
            draw,
            "Stages 2–5 Runic :ro Lock & Self-Healing Hammer Loop",
            "python -m forge.orchestrator --spec spec/acme-incidents.openapi.yaml "
            "--output-dir ./out",
            "MAX_HEAL = 3 · PASS",
        )
        draw.polygon(
            chamfer_rect_coords(52, 152, 520, 412, 14),
            fill=(*RGB_SLAB_INNER, 245),
            outline=(*RGB_MOLTEN_GOLD, 240),
            width=2,
        )
        draw.text(
            (78, 174),
            "DWARVEN VAULT MOUNTS (:ro LOCK vs :rw ANVIL)",
            font=f_mono,
            fill=(*RGB_MOLTEN_GOLD, 255),
        )
        draw.polygon(
            chamfer_rect_coords(78, 212, 468, 152, 10),
            fill=(36, 11, 11, 250),
            outline=(*RGB_EMBER_CRIMSON, 255),
            width=2,
        )
        draw.text(
            (98, 228),
            "RUNIC :ro LOCK — IMMUTABLE BEDROCK",
            font=f_mono,
            fill=(*RGB_EMBER_CRIMSON, 255),
        )
        draw.text(
            (98, 262),
            "pyproject.toml · Dockerfile · forge-manifest.json",
            font=f_mono,
            fill=(*RGB_MITHRIL, 255),
        )
        draw.text(
            (98, 292),
            "src/server.py · src/auth.py · src/deps.py",
            font=f_mono,
            fill=(*RGB_MITHRIL, 255),
        )
        draw.text(
            (98, 322),
            "tests/contract/ · scripts/validate_mcp.py",
            font=f_mono,
            fill=(*RGB_BRIGHT_GOLD, 255),
        )

        draw.polygon(
            chamfer_rect_coords(78, 386, 468, 152, 10),
            fill=(28, 18, 8, 250),
            outline=(*RGB_EMERALD, 255),
            width=2,
        )
        draw.text(
            (98, 402),
            "GLOWING :rw ANVIL OVERLAY — AGENT-WRITABLE",
            font=f_mono,
            fill=(*RGB_EMERALD, 255),
        )
        draw.text(
            (98, 436),
            "src/tools/*.py   (stateless @tool modules)",
            font=f_mono,
            fill=(*RGB_MITHRIL, 255),
        )
        draw.text(
            (98, 466),
            "tests/unit/*.py  (respx >=85% branch cov)",
            font=f_mono,
            fill=(*RGB_MITHRIL, 255),
        )
        draw.text(
            (98, 496),
            "README.md        (setup & mcpServers docs)",
            font=f_mono,
            fill=(*RGB_BRIGHT_GOLD, 255),
        )

        draw.line([(572, 358), (612, 358)], fill=(*RGB_MOLTEN_GOLD, 255), width=6)
        draw.polygon(
            chamfer_rect_coords(612, 152, 536, 412, 14),
            fill=(*RGB_SLAB_INNER, 245),
            outline=(*RGB_FORGE_ORANGE, 245),
            width=2,
        )
        draw.text(
            (638, 174),
            "SELF-HEALING HAMMER LOOP (MAX_HEAL_ITERATIONS = 3)",
            font=f_mono,
            fill=(*RGB_FORGE_ORANGE, 255),
        )
        steps = [
            (
                214,
                88,
                "Hammer Strike 1..3: Synthesize Tools & Tests",
                "--cap-drop=ALL --security-opt=no-new-privileges",
                RGB_MOLTEN_GOLD,
            ),
            (
                322,
                88,
                "Offline Quench Validation (--network=none)",
                "Feeds last 12,000 chars of diagnostics into retry",
                RGB_FORGE_ORANGE,
            ),
            (
                430,
                110,
                "Stage 5: Khazad-dûm Seal & Release Artifacts",
                "forge-release-artifacts.json + AppSec destructiveHint",
                RGB_EMERALD,
            ),
        ]
        for sy, sh, stitle, sdesc, scol in steps:
            draw.polygon(
                chamfer_rect_coords(638, sy, 484, sh, 10),
                fill=(22, 12, 8, 250),
                outline=(*scol, 255),
                width=2,
            )
            draw.text((658, sy + 20), stitle, font=f_card, fill=(*RGB_MITHRIL, 255))
            draw.text((658, sy + 52), sdesc, font=f_mono, fill=(*RGB_STONE_TEXT, 255))

    else:
        _draw_example_header_pil(
            draw,
            "Stage 4 Tempering Harness — 5-Gate MCP 2026-07-28 Verification",
            "python scripts/validate_mcp.py — deterministic zero-network compliance tempering",
            "ALL 5 GATES PASS",
        )
        gates = [
            (
                "GATE 1",
                "Ruff + Bandit",
                "python -m ruff check src tests",
                "Blocks print() stdio corruption & S-bandit issues",
                152,
            ),
            (
                "GATE 2",
                "Mypy --strict",
                "python -m mypy src",
                "Enforces Pydantic v2 typed BaseModel outputSchema",
                234,
            ),
            (
                "GATE 3",
                "AST & SEP-2577 Audit",
                "audit_tools_ast() -> src/tools/",
                "Blocks os/subprocess/open/eval, sample(), injection",
                316,
            ),
            (
                "GATE 4",
                "Pytest 100% Branch Cov",
                "pytest --cov=src/tools --cov-branch",
                "Verifies 2020-12 schemas, x-mcp-header & 100% cov",
                398,
            ),
            (
                "GATE 5",
                "Subprocess STDIO server/discover",
                "PythonStdioTransport -> server/discover",
                "Asserts protocol_version == '2026-07-28' & hygiene",
                480,
            ),
        ]
        draw.line([(119, 152), (119, 548)], fill=(*RGB_MOLTEN_GOLD, 255), width=4)
        for code, gtitle, cmd, desc, y in gates:
            draw.polygon(
                chamfer_rect_coords(52, y, 1096, 68, 10),
                fill=(*RGB_SLAB_INNER, 245),
                outline=(*RGB_MOLTEN_GOLD, 225),
                width=2,
            )
            draw.polygon(
                chamfer_rect_coords(70, y + 16, 98, 36, 6),
                fill=(40, 19, 9, 255),
                outline=(*RGB_FORGE_ORANGE, 255),
                width=2,
            )
            _draw_centered_text(draw, 119, y + 34, code, f_tag, (*RGB_BRIGHT_GOLD, 255))
            draw.text((188, y + 14), gtitle, font=f_card, fill=(*RGB_MITHRIL, 255))
            draw.text((188, y + 40), desc, font=f_body, fill=(*RGB_STONE_TEXT, 255))
            _draw_right_text(draw, 1036, y + 26, cmd, f_mono, (*RGB_BRIGHT_GOLD, 255))
            draw.polygon(
                chamfer_rect_coords(1054, y + 17, 76, 34, 6),
                fill=(7, 36, 26, 255),
                outline=(*RGB_EMERALD, 255),
                width=2,
            )
            _draw_centered_text(draw, 1092, y + 34, "PASS", f_tag, (*RGB_EMERALD, 255))

    png_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(png_path, format="PNG", optimize=True)


def _try_external_svg_rasterizer(svg_path: Path, png_path: Path, width: int) -> bool:
    """Use resolved CLI SVG rasterizer path when present; else False for Pillow."""
    inkscape_bin = shutil.which("inkscape")
    if inkscape_bin:
        subprocess.run(
            [
                inkscape_bin,
                str(svg_path),
                "--export-type=png",
                f"--export-filename={png_path}",
                f"--export-width={width}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    rsvg_bin = shutil.which("rsvg-convert")
    if rsvg_bin:
        subprocess.run(
            [rsvg_bin, "-w", str(width), "-o", str(png_path), str(svg_path)],
            check=True,
        )
        return True
    magick_bin = shutil.which("magick")
    if magick_bin:
        subprocess.run(
            [
                magick_bin,
                "-background",
                "none",
                str(svg_path),
                "-resize",
                f"{width}x",
                str(png_path),
            ],
            check=True,
        )
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render Khazad-dûm Dwarven Forge SVG + PNG brand and architecture visuals."
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress summary line")
    args = parser.parse_args()

    stats = load_repo_stats()

    # 1. Square icons (512x512): assets/logo.{svg,png} & docs/assets/icon.{svg,png}
    sq_svg = build_square_icon_svg()
    for svg_p, png_p in [
        (ROOT_ASSETS / "logo.svg", ROOT_ASSETS / "logo.png"),
        (DOCS_ASSETS / "icon.svg", DOCS_ASSETS / "icon.png"),
    ]:
        svg_p.parent.mkdir(parents=True, exist_ok=True)
        svg_p.write_text(sq_svg, encoding="utf-8")
        if not _try_external_svg_rasterizer(svg_p, png_p, 512):
            _render_square_icon_png(png_p)

    # 2. Wide Hero Banner (1200x380): docs/assets/logo.{svg,png}
    hero_svg = build_hero_logo_svg(stats)
    hero_svg_p = DOCS_ASSETS / "logo.svg"
    hero_png_p = DOCS_ASSETS / "logo.png"
    hero_svg_p.parent.mkdir(parents=True, exist_ok=True)
    hero_svg_p.write_text(hero_svg, encoding="utf-8")
    if not _try_external_svg_rasterizer(hero_svg_p, hero_png_p, 1200):
        _render_hero_banner_png(hero_png_p, stats)

    # 3. Category Stage Icons (64x64 SVG + 256x256 PNG)
    for kind in ("ingest", "template", "sandbox", "verify", "govern"):
        csvg = build_category_icon_svg(kind)
        c_svg_p = ICONS_DIR / f"icon-{kind}.svg"
        c_png_p = ICONS_DIR / f"icon-{kind}.png"
        c_svg_p.parent.mkdir(parents=True, exist_ok=True)
        c_svg_p.write_text(csvg, encoding="utf-8")
        if not _try_external_svg_rasterizer(c_svg_p, c_png_p, 256):
            _render_category_icon_png(c_png_p, kind)

    # 4. Graphic Workflow & Architecture Examples (1200x620)
    examples = [
        ("architecture-overview", build_architecture_overview_svg(stats)),
        ("workflow-openapi-ingest", build_workflow_ingest_svg()),
        ("workflow-self-healing-sandbox", build_workflow_sandbox_svg()),
        ("workflow-mcp-2026-gates", build_workflow_gates_svg()),
    ]
    for slug, content in examples:
        ex_svg_p = EXAMPLES_DIR / f"{slug}.svg"
        ex_png_p = EXAMPLES_DIR / f"{slug}.png"
        ex_svg_p.parent.mkdir(parents=True, exist_ok=True)
        ex_svg_p.write_text(content, encoding="utf-8")
        if not _try_external_svg_rasterizer(ex_svg_p, ex_png_p, 1200):
            _render_example_png(ex_png_p, slug, stats)

    if not args.quiet:
        print(
            "Rendered 12 SVG + 12 PNG Khazad-dûm Dwarven Forge visual assets for MCP Server Forge."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
