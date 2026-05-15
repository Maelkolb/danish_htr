"""Rebuild the HTML viewer from an existing pipeline output directory.

Use this to regenerate the HTML without re-running the Gemini transcription.
Reads the enhanced images, per-page markdown transcripts, and TEI XML files
that are already on disk from a previous pipeline run.

Usage
-----
    # From the repo root, point at a doc directory:
    python rebuild_html.py output/my_letter_1841

    # Explicit output path:
    python rebuild_html.py output/my_letter_1841 --out output/my_letter_1841/review_v2.html

    # In a Colab/Jupyter cell:
    %run rebuild_html.py output/my_letter_1841

Expected directory layout (created by run.py / DocumentTranscriber)
---------------------------------------------------------------------
    output/
      {stem}/
        enhanced/            ← page images fed to HTML; falls back to raw/
          {stem}_page_001.png
          {stem}_page_002.png
          …
        transcripts/
          {stem}_page_001.md
          …
        tei/
          {stem}_page_001.xml
          …
        {stem}.html          ← overwritten (or --out path)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.html_generator import generate_html
from pipeline.tei_converter import parse_front_matter


# ── helpers ───────────────────────────────────────────────────────────────────

def _page_number(path: Path) -> int:
    """Extract the 1-based page number from a filename like stem_page_007.png."""
    m = re.search(r"_page_(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def collect_pages(doc_dir: Path) -> list[dict]:
    """Scan *doc_dir* and return a list of page dicts suitable for generate_html."""
    doc_dir = doc_dir.resolve()
    stem = doc_dir.name

    # Images: prefer enhanced/, fall back to raw/
    for img_subdir in ("enhanced", "raw"):
        img_dir = doc_dir / img_subdir
        images = sorted(img_dir.glob("*.png"), key=_page_number) if img_dir.is_dir() else []
        if images:
            break
    else:
        raise FileNotFoundError(
            f"No images found in {doc_dir}/enhanced/ or {doc_dir}/raw/.\n"
            "Make sure you ran the full pipeline at least once."
        )

    transcript_dir = doc_dir / "transcripts"
    tei_dir = doc_dir / "tei"

    pages = []
    for img_path in images:
        page_num = _page_number(img_path)

        # Markdown transcript
        md_path = transcript_dir / f"{stem}_page_{page_num:03d}.md"
        md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

        # TEI XML
        tei_path = tei_dir / f"{stem}_page_{page_num:03d}.xml"
        tei_text = tei_path.read_text(encoding="utf-8") if tei_path.exists() else ""

        pages.append(
            {
                "page": page_num,
                "image": img_path,
                "markdown_text": md_text,
                "tei_text": tei_text,
            }
        )

    return pages


# ── main ──────────────────────────────────────────────────────────────────────

def rebuild(doc_dir: Path | str, out_path: Path | str | None = None) -> Path:
    """Rebuild the HTML viewer for *doc_dir* and return the output path.

    Can be called directly from a notebook::

        from rebuild_html import rebuild
        rebuild("output/my_letter_1841")
    """
    doc_dir = Path(doc_dir).resolve()
    if not doc_dir.is_dir():
        raise NotADirectoryError(doc_dir)

    stem = doc_dir.name
    out_path = Path(out_path) if out_path else doc_dir / f"{stem}.html"

    print(f"Scanning  : {doc_dir}", flush=True)
    pages = collect_pages(doc_dir)
    print(f"Found     : {len(pages)} page(s)", flush=True)

    # Pull title / meta from the first page's front-matter (if any)
    first_md = pages[0]["markdown_text"] if pages else ""
    front, _ = parse_front_matter(first_md)
    meta_str = " · ".join(
        f"{k}: {v}"
        for k, v in front.items()
        if k in ("place", "date", "sender", "addressee") and str(v).strip() not in ("", "?")
    )

    print(f"Building  : {out_path}", flush=True)
    generate_html(stem, pages, out_path, meta=meta_str)

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"Done ✓     {out_path}  ({size_mb:.1f} MB)", flush=True)
    return out_path


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Rebuild the HTML viewer from an existing pipeline output directory."
    )
    p.add_argument(
        "doc_dir",
        type=Path,
        help="Path to the document directory, e.g. output/my_letter_1841",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output HTML path (default: <doc_dir>/<stem>.html, overwriting the existing file)",
    )
    args = p.parse_args()

    try:
        rebuild(args.doc_dir, args.out)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
