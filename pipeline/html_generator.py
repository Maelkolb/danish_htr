"""Generate a self-contained split-panel HTML review viewer.

Layout:

    ┌──────────────────────────────────────────────────────────────────┐
    │ <title>  meta info             [Page 1] [Page 2] [Page 3]        │
    ├──────────────────────────────┬───────────────────────────────────┤
    │                              │  [Markdown] [TEI XML]             │
    │   scanned page image         │ ─────────────────────────────────│
    │   (pan & zoom)               │  …transcript…                     │
    │                              │                                   │
    └──────────────────────────────┴───────────────────────────────────┘

Images are base64-embedded so the file is single-artifact (no broken
links when emailed or zipped). For a 20-page document at ~1MB/page this
yields a ~30MB HTML — still fine for a browser, but if you need lighter
output, swap the embed for relative ``<img src='…'>`` links.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Dict, List

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #f5f1ea;
    --panel: #fdfcf8;
    --ink: #2a2620;
    --muted: #7d6f5a;
    --accent: #6b4423;
    --accent-soft: #8a5a30;
    --border: #d9cfbf;
    --img-bg: #1d1a16;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; }
  body {
    font-family: 'Iowan Old Style', 'Palatino', 'Georgia', serif;
    background: var(--bg);
    color: var(--ink);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  header {
    flex: 0 0 auto;
    padding: 0.7rem 1.25rem;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }
  header h1 {
    font-size: 1.05rem;
    margin: 0;
    font-weight: 500;
    letter-spacing: 0.01em;
  }
  header .meta {
    color: var(--muted);
    font-size: 0.85rem;
    font-style: italic;
  }
  .pages-nav {
    margin-left: auto;
    display: flex;
    gap: 0.25rem;
    flex-wrap: wrap;
  }
  .pages-nav button {
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--ink);
    padding: 0.3rem 0.7rem;
    cursor: pointer;
    font-family: inherit;
    font-size: 0.85rem;
    border-radius: 3px;
    transition: background 0.12s, color 0.12s;
  }
  .pages-nav button:hover {
    background: var(--bg);
  }
  .pages-nav button.active {
    background: var(--accent);
    color: var(--panel);
    border-color: var(--accent);
  }
  main {
    flex: 1 1 auto;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    min-height: 0;
  }
  .panel {
    overflow: hidden;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .panel.left {
    background: var(--img-bg);
    align-items: center;
    justify-content: flex-start;
    overflow: auto;
    padding: 1.5rem;
  }
  .panel.left .page-section {
    display: none;
  }
  .panel.left .page-section.active {
    display: block;
  }
  .panel.left img {
    max-width: 100%;
    height: auto;
    box-shadow: 0 6px 24px rgba(0,0,0,0.45);
    background: #fff;
  }
  .panel.right {
    border-left: 1px solid var(--border);
    background: var(--panel);
  }
  .tabs {
    display: flex;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    flex: 0 0 auto;
  }
  .tabs button {
    flex: 1;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 0.7rem 1rem;
    cursor: pointer;
    font-family: inherit;
    font-size: 0.9rem;
    color: var(--muted);
    letter-spacing: 0.02em;
    transition: color 0.12s, border-color 0.12s;
  }
  .tabs button:hover { color: var(--accent-soft); }
  .tabs button.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
    background: var(--panel);
  }
  .tab-content {
    flex: 1 1 auto;
    overflow: auto;
    padding: 1.5rem 2rem;
    min-height: 0;
  }
  .tab-content[hidden] { display: none; }
  .tab-content .page-section { display: none; }
  .tab-content .page-section.active { display: block; }
  pre {
    background: var(--bg);
    border: 1px solid var(--border);
    padding: 1rem 1.25rem;
    border-radius: 4px;
    overflow: auto;
    font-size: 0.85rem;
    line-height: 1.55;
    font-family: 'SF Mono', 'JetBrains Mono', 'Menlo', monospace;
    white-space: pre-wrap;
    word-wrap: break-word;
    color: var(--ink);
  }
  .empty {
    color: var(--muted);
    font-style: italic;
  }
  footer {
    flex: 0 0 auto;
    padding: 0.4rem 1.25rem;
    border-top: 1px solid var(--border);
    background: var(--panel);
    color: var(--muted);
    font-size: 0.75rem;
    text-align: right;
  }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="meta">__META__</span>
  <div class="pages-nav">__PAGE_BUTTONS__</div>
</header>
<main>
  <div class="panel left">__IMAGES__</div>
  <div class="panel right">
    <div class="tabs">
      <button class="tab-btn active" data-tab="md">Markdown</button>
      <button class="tab-btn" data-tab="tei">TEI XML</button>
    </div>
    <div class="tab-content" id="tab-md">__MD_SECTIONS__</div>
    <div class="tab-content" id="tab-tei" hidden>__TEI_SECTIONS__</div>
  </div>
</main>
<footer>__FOOTER__</footer>

<script>
  (function() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(b => b.addEventListener('click', () => {
      tabBtns.forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      document.getElementById('tab-md').hidden = b.dataset.tab !== 'md';
      document.getElementById('tab-tei').hidden = b.dataset.tab !== 'tei';
    }));

    const pageBtns = document.querySelectorAll('.page-btn');
    function showPage(n) {
      pageBtns.forEach(b => b.classList.toggle('active', b.dataset.page === n));
      document.querySelectorAll('.page-section').forEach(s => {
        s.classList.toggle('active', s.dataset.page === n);
      });
    }
    pageBtns.forEach(b => b.addEventListener('click', () => showPage(b.dataset.page)));
    if (pageBtns.length) showPage(pageBtns[0].dataset.page);

    // Arrow key navigation between pages
    document.addEventListener('keydown', e => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      const buttons = Array.from(pageBtns);
      const activeIdx = buttons.findIndex(b => b.classList.contains('active'));
      if (activeIdx === -1) return;
      const nextIdx = e.key === 'ArrowLeft'
        ? Math.max(0, activeIdx - 1)
        : Math.min(buttons.length - 1, activeIdx + 1);
      buttons[nextIdx].click();
    });
  })();
</script>
</body>
</html>
"""


def _embed_image(image_path: Path) -> str:
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    suffix = image_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{data}"


def generate_html(
    title: str,
    pages: List[Dict],
    output_path: Path | str,
    *,
    meta: str = "",
    footer: str = "Transcribed with Gemini 3 · review before citing",
) -> Path:
    """Render a self-contained split-panel viewer.

    ``pages`` is a list of dicts, one per page:
        {
            "page": int,                 # 1-indexed page number
            "image": Path,               # enhanced page image
            "markdown_text": str,        # transcription markdown
            "tei_text": str,             # TEI XML
        }
    """
    output_path = Path(output_path)

    page_buttons_parts: List[str] = []
    image_parts: List[str] = []
    md_parts: List[str] = []
    tei_parts: List[str] = []

    for i, p in enumerate(pages):
        n = str(p["page"])
        active = "active" if i == 0 else ""

        page_buttons_parts.append(
            f'<button class="page-btn {active}" data-page="{n}">{n}</button>'
        )

        img_data = _embed_image(Path(p["image"]))
        image_parts.append(
            f'<div class="page-section {active}" data-page="{n}">'
            f'<img src="{img_data}" alt="Page {n}">'
            f'</div>'
        )

        md_text = p.get("markdown_text") or ""
        md_parts.append(
            f'<div class="page-section {active}" data-page="{n}">'
            f'<pre>{html.escape(md_text) or "<em class=empty>(no transcription)</em>"}</pre>'
            f'</div>'
        )

        tei_text = p.get("tei_text") or ""
        tei_parts.append(
            f'<div class="page-section {active}" data-page="{n}">'
            f'<pre>{html.escape(tei_text) or "<em class=empty>(no TEI output)</em>"}</pre>'
            f'</div>'
        )

    html_out = (
        _HTML_TEMPLATE.replace("__TITLE__", html.escape(title))
        .replace("__META__", html.escape(meta))
        .replace("__PAGE_BUTTONS__", "\n".join(page_buttons_parts))
        .replace("__IMAGES__", "\n".join(image_parts))
        .replace("__MD_SECTIONS__", "\n".join(md_parts))
        .replace("__TEI_SECTIONS__", "\n".join(tei_parts))
        .replace("__FOOTER__", html.escape(footer))
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_out, encoding="utf-8")
    return output_path
