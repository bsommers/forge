"""Automated documentation alignment, relative link, and SVG/PNG graphic verification suite."""

from __future__ import annotations

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

EXPECTED_DUAL_ASSETS = [
    ROOT / "assets" / "logo",
    ROOT / "docs" / "assets" / "icon",
    ROOT / "docs" / "assets" / "logo",
    ROOT / "docs" / "assets" / "icons" / "icon-ingest",
    ROOT / "docs" / "assets" / "icons" / "icon-template",
    ROOT / "docs" / "assets" / "icons" / "icon-sandbox",
    ROOT / "docs" / "assets" / "icons" / "icon-verify",
    ROOT / "docs" / "assets" / "icons" / "icon-govern",
    ROOT / "docs" / "assets" / "examples" / "architecture-overview",
    ROOT / "docs" / "assets" / "examples" / "workflow-openapi-ingest",
    ROOT / "docs" / "assets" / "examples" / "workflow-self-healing-sandbox",
    ROOT / "docs" / "assets" / "examples" / "workflow-mcp-2026-gates",
]

EXPECTED_ILLUSTRATIONS = [
    ROOT / "docs" / "assets" / "khazad-dum-hero.png",
    ROOT / "docs" / "assets" / "dwarven-anvil-emblem.png",
    ROOT / "docs" / "assets" / "khazad-dum-pipeline.png",
]

LIVING_MARKDOWN_DOCS = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "GEMINI.md",
    ROOT / "CHANGELOG.md",
    ROOT / "spec" / "README.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "PURPOSE.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "SECURE_DESIGN_PATTERNS.md",
    ROOT / "docs" / "ECOSYSTEM_VALUE_AND_RELEVANCE.md",
    ROOT / "docs" / "HOWTO.md",
    ROOT / "docs" / "ROADMAP.md",
    ROOT / "docs" / "CHECKPOINT.md",
    ROOT / "docs" / "plans" / "01-high-signal-codegen-and-agent-refinement.md",
    ROOT / "docs" / "plans" / "02-per-operation-auth-and-multi-tag-sharding.md",
    ROOT / "docs" / "plans" / "03-wild-openapi-resilience-composite-tools-and-hardened-bounds.md",
    ROOT / "docs" / "plans" / "04-research-spike-nist-800-53-cosis-attestation.md",
    ROOT / "docs" / "brochure.md",
    ROOT / "docs" / "user-guide" / "README.md",
    ROOT / "docs" / "user-guide" / "01-getting-started.md",
    ROOT / "docs" / "user-guide" / "02-forging-servers.md",
    ROOT / "docs" / "user-guide" / "03-mcp-2026-07-28-authoring.md",
    ROOT / "docs" / "user-guide" / "04-cli-and-config-reference.md",
    ROOT / "docs" / "user-guide" / "05-troubleshooting-and-faq.md",
]

MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(((?:[^()]|\([^()]*\))+)\)")
HTML_ATTR_RE = re.compile(r'(?:src|href)="([^"]+)"')
EXTERNAL_SVG_REF_RE = re.compile(r'(?:href|src)\s*=\s*["\']https?://|url\(\s*["\']?https?://', re.I)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _strip_fenced_code(md_text: str) -> str:
    return re.sub(r"```.*?```", "", md_text, flags=re.DOTALL)


def test_svg_and_png_assets_are_valid_and_self_contained() -> None:
    for base in EXPECTED_DUAL_ASSETS:
        svg_path = base.with_suffix(".svg")
        png_path = base.with_suffix(".png")
        assert svg_path.exists(), f"Missing SVG asset: {svg_path}"
        assert png_path.exists(), f"Missing PNG asset: {png_path}"

        svg_text = svg_path.read_text(encoding="utf-8")
        root = ET.fromstring(svg_text)  # noqa: S314
        assert root.tag.endswith("svg"), f"Invalid root SVG element in {svg_path}"
        assert "@import" not in svg_text, f"External @import forbidden in {svg_path}"
        assert not EXTERNAL_SVG_REF_RE.search(svg_text), (
            f"External network resource reference forbidden inside {svg_path}"
        )

        png_bytes = png_path.read_bytes()
        assert len(png_bytes) > 64, f"Empty PNG asset: {png_path}"
        assert png_bytes.startswith(PNG_MAGIC), f"Invalid PNG magic header in {png_path}"

    for illust in EXPECTED_ILLUSTRATIONS:
        assert illust.exists(), f"Missing Khazad-dum illustration: {illust}"
        data = illust.read_bytes()
        assert data.startswith(PNG_MAGIC), f"Illustration is not valid PNG: {illust}"


def test_living_markdown_and_pages_have_zero_broken_relative_links() -> None:
    for doc_path in LIVING_MARKDOWN_DOCS:
        assert doc_path.exists(), f"Missing required living doc: {doc_path}"
        cleaned = _strip_fenced_code(doc_path.read_text(encoding="utf-8"))
        for match in MD_LINK_RE.finditer(cleaned):
            raw_target = match.group(1).strip()
            if not raw_target or raw_target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            rel_part = urllib.parse.unquote(raw_target.split("#", 1)[0])
            if not rel_part:
                continue
            resolved = (doc_path.parent / rel_part).resolve()
            assert resolved.exists(), f"Broken link in {doc_path.relative_to(ROOT)}: {raw_target}"

    pages_html = ROOT / "docs" / "index.html"
    assert pages_html.exists()
    assert (ROOT / "docs" / ".nojekyll").exists()
    for match in HTML_ATTR_RE.finditer(pages_html.read_text(encoding="utf-8")):
        raw_target = match.group(1).strip()
        if not raw_target or raw_target.startswith(("#", "http://", "https://", "data:")):
            continue
        resolved = (pages_html.parent / urllib.parse.unquote(raw_target.split("#", 1)[0])).resolve()
        assert resolved.exists(), f"Broken HTML asset/link in docs/index.html: {raw_target}"


def test_manifest_tool_count_matches_readme_table() -> None:
    manifest = json.loads((ROOT / "forge-manifest.json").read_text(encoding="utf-8"))
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    for tool_entry in manifest["tools"]:
        assert f"`{tool_entry['name']}`" in readme_text
