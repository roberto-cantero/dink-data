"""Build docs/DinkData-Design.pdf from docs/DESIGN.md.

The Markdown file is the source of truth. This script renders it to HTML, prints the HTML
to PDF with headless Chrome or Chromium, and shrinks the PDF with PyMuPDF.

Usage: make design-pdf
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin

DOCS = Path(__file__).resolve().parent.parent / "docs"
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
]
SVG_WIDTHS = {"court": "40%", "feedback_loop": "72%", "rally_grammar": "92%"}

CSS = """
@page {
  size: A4;
  margin: 16mm 15mm 16mm 15mm;
  @bottom-center {
    content: "DinkData design document  ·  page " counter(page) " of " counter(pages);
    font: 8pt "Helvetica Neue", sans-serif; color: #64748b;
  }
}
@page :first { @bottom-center { content: none; } }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
svg, svg text { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif !important; }
em { font-style: normal; }
body { font: 9.4pt/1.38 "Helvetica Neue", Helvetica, Arial, sans-serif; color: #0f172a; }
h1 { font-size: 26pt; margin: 0 0 4pt; color: #0f172a; }
h1 + p { font-size: 12pt; color: #334155; }
h2 { font-size: 16pt; color: #1d4ed8; border-bottom: 2px solid #bfdbfe; padding-bottom: 3pt;
     margin: 20pt 0 6pt; break-after: avoid; }
h3 { font-size: 11.5pt; color: #0f172a; margin: 12pt 0 3pt; break-after: avoid; }
h4 { font-size: 11pt; margin: 12pt 0 4pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #1d4ed8; text-decoration: none; word-break: break-all; }
code { font: 8.6pt "SF Mono", Menlo, Consolas, monospace; background: #f1f5f9;
       padding: 0 2pt; border-radius: 3px; }
pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8pt 10pt;
      font-size: 8.2pt; line-height: 1.35; white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8.2pt; }
table { border-collapse: collapse; width: 100%; margin: 5pt 0 8pt; font-size: 8.1pt;
        line-height: 1.35; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #eff6ff; color: #1e3a8a; text-align: left; font-weight: 600; }
th, td { border: 1px solid #cbd5e1; padding: 3pt 5pt; vertical-align: top; }
tbody tr:nth-child(even) td { background: #f8fafc; }
img { display: block; width: 100%; margin: 8pt auto 2pt; break-inside: avoid; }
img + em, p > em:only-child {
  display: block; text-align: center; color: #475569; font-size: 8.8pt;
}
hr { display: none; }
blockquote { border-left: 3px solid #93c5fd; margin: 6pt 0; padding: 2pt 10pt; color: #334155; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; }
.cover .brand { font-size: 11pt; letter-spacing: 3pt; color: #1d4ed8; font-weight: 700; }
.cover h1 { font-size: 34pt; margin: 8pt 0; }
.cover .sub { font-size: 13pt; color: #334155; max-width: 140mm; }
.cover .meta { margin-top: 28pt; font-size: 10pt; color: #475569; line-height: 1.8; }
.cover .bar { height: 6px; width: 90mm; background: linear-gradient(90deg,#1d4ed8,#22c55e,#f97316);
              margin: 18pt 0; border-radius: 3px; }
"""

COVER_TEMPLATE = """
<section class="cover">
  <div class="brand">DINKDATA</div>
  <h1>Design document</h1>
  <div class="sub">Product requirements, technical design and system design for
  DinkData, which turns PickleCam videos into per-player pickleball stats and highlight
  reels.</div>
  <div class="bar"></div>
  <div class="meta">
    Version {version}<br>
    {date}<br>
    Owners: Robby and Marti<br>
    Prepared with Claude Code<br>
    Source: <code>docs/DESIGN.md</code>
  </div>
</section>
"""


def find_chrome() -> str:
    """Return a Chrome or Chromium executable, preferring the CHROME environment variable."""
    for candidate in [os.environ.get("CHROME", ""), *CHROME_CANDIDATES]:
        if candidate and (Path(candidate).exists() or shutil.which(candidate)):
            return candidate
    sys.exit("Chrome or Chromium not found. Set CHROME to its path.")


def metadata(text: str, field: str) -> str:
    """Read a value such as the version from the table at the top of DESIGN.md."""
    match = re.search(rf"^\| {field} \| (.+?) \|$", text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def inline_svg(match: re.Match[str]) -> str:
    """Inline a diagram, so the PDF embeds each font once instead of once per image."""
    name = match.group(1)
    svg = (DOCS / "diagrams" / f"{name}.svg").read_text(encoding="utf-8")
    svg = re.sub(r'\swidth="\d+"\s+height="\d+"', "", svg, count=1)
    svg = svg.replace("<svg ", '<svg style="width:100%;height:auto;display:block" ', 1)
    width = SVG_WIDTHS.get(name, "100%")
    return f'<div style="width:{width};margin:8pt auto 2pt;break-inside:avoid">{svg}</div>'


def build_html(text: str) -> str:
    """Render DESIGN.md to one HTML page with a cover."""
    head, rest = text.split("\n## 1. Summary", 1)
    head = re.sub(r"^# .*\n", "", head, count=1)
    head = "## About this document\n" + head.replace("\n## Contents\n", "\n### Contents\n")
    md = MarkdownIt("commonmark", {"html": True}).enable("table")
    md.use(anchors_plugin, min_level=2, max_level=3)
    body = md.render(head + "\n## 1. Summary" + rest)
    body = re.sub(r"<thead>\s*<tr>\s*(?:<th></th>\s*)+</tr>\s*</thead>", "", body)
    body = re.sub(r'<img src="diagrams/([a-z_]+)\.svg"[^>]*>', inline_svg, body)
    cover = COVER_TEMPLATE.format(version=metadata(text, "Version"), date=metadata(text, "Date"))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>DinkData design document</title>"
        f"<style>{CSS}</style></head><body>{cover}{body}</body></html>"
    )


def main() -> None:
    text = (DOCS / "DESIGN.md").read_text(encoding="utf-8")
    out = DOCS / "DinkData-Design.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "design.html"
        raw_pdf = Path(tmp) / "raw.pdf"
        html_path.write_text(build_html(text), encoding="utf-8")
        subprocess.run(
            [
                find_chrome(),
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--disable-pdf-tagging",
                f"--print-to-pdf={raw_pdf}",
                html_path.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
        doc = pymupdf.open(raw_pdf)
        doc.subset_fonts()
        doc.ez_save(out, garbage=4, deflate=True, clean=True)
    print(f"{out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
