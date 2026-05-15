"""Top-level orchestration: PDF in → markdown + TEI + HTML out.

This is the function you call from the Colab notebook. It also runs as
a CLI:

    python run.py path/to/letter.pdf --output ./out --thinking medium
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from pipeline.gemini_client import GeminiTranscriber
from pipeline.html_generator import generate_html
from pipeline.tei_converter import markdown_to_tei, parse_front_matter
from pipeline.transcriber import DocumentResult, DocumentTranscriber


@dataclass
class PipelineOutputs:
    document: DocumentResult
    tei_dir: Path
    tei_files: List[Path]
    html_path: Path


def run(
    pdf_path: Path | str,
    output_dir: Path | str = "./output",
    model: str = "gemini-3.1-flash-lite",
    thinking: str = "medium",
    media_resolution: str = "media_resolution_high",
    enhance: bool = True,
    dpi: int = 400,
    api_key: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> PipelineOutputs:
    """Run the full pipeline on a single PDF and return all artefact paths.

    Parameters
    ----------
    pdf_path        : input PDF
    output_dir      : work + output directory
    model           : Gemini model id; gemini-3.1-flash-lite is the default,
                      bump to gemini-3.1-pro-preview for the worst pages
    thinking        : thinking_level — minimal | low | medium | high
    media_resolution: media_resolution_low | _medium | _high | _ultra_high
                      _high (1120 tok/img) is recommended for handwriting
    enhance         : apply CLAHE + bilateral filter before sending
    api_key         : Gemini API key; falls back to $GEMINI_API_KEY
    progress        : optional callback(str) for log messages
    """
    progress = progress or (lambda msg: print(msg, file=sys.stderr))
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)

    gemini = GeminiTranscriber(
        api_key=api_key,
        model=model,
        thinking_level=thinking,
        media_resolution=media_resolution,
    )
    transcriber = DocumentTranscriber(
        gemini=gemini,
        work_dir=output_dir,
        enhance=enhance,
        dpi=dpi,
        progress_callback=progress,
    )

    # 1–4: split, enhance, transcribe, combine
    doc = transcriber.process_pdf(pdf_path)

    # 5: per-page TEI XML
    progress("Converting markdown → TEI XML")
    tei_dir = doc.doc_dir / "tei"
    tei_dir.mkdir(exist_ok=True)
    tei_files: List[Path] = []
    page_records = []
    for page in doc.pages:
        tei_xml = markdown_to_tei(page.text, source_filename=pdf_path.name)
        tei_path = tei_dir / f"{doc.stem}_page_{page.page:03d}.xml"
        tei_path.write_text(tei_xml, encoding="utf-8")
        tei_files.append(tei_path)
        page_records.append(
            {
                "page": page.page,
                "image": page.image,
                "markdown_text": page.text,
                "tei_text": tei_xml,
            }
        )

    # 6: split-panel HTML viewer
    progress("Building split-panel HTML viewer")
    first_meta, _ = parse_front_matter(doc.pages[0].text) if doc.pages else ({}, "")
    title = doc.stem
    meta_str = " · ".join(
        f"{k}: {v}"
        for k, v in first_meta.items()
        if k in ("place", "date", "sender", "addressee") and str(v).strip() not in {"", "?"}
    )
    html_path = doc.doc_dir / f"{doc.stem}.html"
    generate_html(title, page_records, html_path, meta=meta_str)

    progress("Done.")
    return PipelineOutputs(
        document=doc,
        tei_dir=tei_dir,
        tei_files=tei_files,
        html_path=html_path,
    )


# ---------------------------------------------------------------------- #
def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Transcribe a Danish handwritten PDF to markdown + TEI XML."
    )
    p.add_argument("pdf", type=Path, help="Input PDF")
    p.add_argument("--output", "-o", type=Path, default=Path("./output"))
    p.add_argument("--model", default="gemini-3.1-flash-lite")
    p.add_argument(
        "--thinking",
        default="medium",
        choices=["minimal", "low", "medium", "high"],
    )
    p.add_argument(
        "--media-resolution",
        default="media_resolution_high",
        choices=[
            "media_resolution_low",
            "media_resolution_medium",
            "media_resolution_high",
        ],
    )
    p.add_argument(
        "--no-enhance",
        action="store_true",
        help="Skip CLAHE / bilateral filtering",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=400,
        help="Rasterisation DPI (default 400; raise for very small/dense script)",
    )
    p.add_argument(
        "--api-key",
        help="Gemini API key (default: $GEMINI_API_KEY)",
    )
    args = p.parse_args()

    if not args.pdf.exists():
        print(f"error: PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    out = run(
        pdf_path=args.pdf,
        output_dir=args.output,
        model=args.model,
        thinking=args.thinking,
        media_resolution=args.media_resolution,
        enhance=not args.no_enhance,
        dpi=args.dpi,
        api_key=args.api_key,
    )

    print()
    print("Transcription complete.")
    print(f"  Combined markdown : {out.document.combined_markdown}")
    print(f"  TEI XML directory : {out.tei_dir}")
    print(f"  HTML review viewer: {out.html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
