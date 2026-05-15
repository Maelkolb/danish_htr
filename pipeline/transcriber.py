"""End-to-end pipeline: PDF → page images → enhanced images → markdown.

Typical use:

    from pipeline import DocumentTranscriber, GeminiTranscriber

    gemini = GeminiTranscriber(thinking_level="medium")
    pipe = DocumentTranscriber(gemini=gemini, work_dir="./out")
    result = pipe.process_pdf("1841_letter.pdf")
    print(result["combined_markdown"])
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .gemini_client import GeminiTranscriber
from .image_enhancer import enhance_image
from .pdf_processor import pdf_to_images
from .prompts import TRANSCRIPTION_PROMPT


@dataclass
class PageResult:
    page: int
    raw_image: Path
    image: Path           # enhanced image, or == raw_image when enhance=False
    markdown_path: Path
    text: str


@dataclass
class DocumentResult:
    stem: str
    source_pdf: Path
    doc_dir: Path
    pages: List[PageResult] = field(default_factory=list)
    combined_markdown: Optional[Path] = None


class DocumentTranscriber:
    """Run the full pipeline on a single PDF."""

    def __init__(
        self,
        gemini: Optional[GeminiTranscriber] = None,
        work_dir: Path | str = "./work",
        enhance: bool = True,
        dpi: int = 400,
        prompt: str = TRANSCRIPTION_PROMPT,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.gemini = gemini or GeminiTranscriber()
        self.work_dir = Path(work_dir)
        self.enhance = enhance
        self.dpi = dpi
        self.prompt = prompt
        self._progress = progress_callback or (lambda msg: None)

    # ------------------------------------------------------------------ #
    def process_pdf(self, pdf_path: Path | str) -> DocumentResult:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)

        stem = pdf_path.stem
        doc_dir = self.work_dir / stem
        raw_dir = doc_dir / "raw"
        enhanced_dir = doc_dir / "enhanced"
        transcript_dir = doc_dir / "transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)

        # 1. Split PDF into page images
        self._progress(f"Rendering {pdf_path.name} → page images")
        raw_pages = pdf_to_images(pdf_path, raw_dir, dpi=self.dpi)
        self._progress(f"  {len(raw_pages)} page(s) rendered")

        # 2. Enhance each page (optional)
        if self.enhance:
            self._progress("Enhancing page images (CLAHE + bilateral)")
            pages = [
                enhance_image(p, enhanced_dir / p.name) for p in raw_pages
            ]
        else:
            pages = raw_pages

        # 3. Transcribe each page
        results: List[PageResult] = []
        for i, (raw_p, enh_p) in enumerate(zip(raw_pages, pages), start=1):
            self._progress(f"Transcribing page {i}/{len(pages)} …")
            text = self.gemini.transcribe_image(enh_p, self.prompt)
            md_path = transcript_dir / f"{stem}_page_{i:03d}.md"
            md_path.write_text(text, encoding="utf-8")
            results.append(
                PageResult(
                    page=i,
                    raw_image=raw_p,
                    image=enh_p,
                    markdown_path=md_path,
                    text=text,
                )
            )

        # 4. Combine page transcripts into a single markdown file
        combined = _combine_pages([r.text for r in results], pages_info=results)
        combined_path = doc_dir / f"{stem}.md"
        combined_path.write_text(combined, encoding="utf-8")
        self._progress(f"Wrote combined markdown → {combined_path}")

        return DocumentResult(
            stem=stem,
            source_pdf=pdf_path,
            doc_dir=doc_dir,
            pages=results,
            combined_markdown=combined_path,
        )


# ---------------------------------------------------------------------- #
_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _combine_pages(texts: List[str], pages_info: List[PageResult]) -> str:
    """Join per-page transcripts into one document.

    The first page's YAML front matter is kept as the document header.
    Subsequent pages have their front matter stripped and are preceded
    by an HTML comment marking the page number, which survives most
    Markdown→HTML pipelines as a structural anchor without being shown.
    """
    if not texts:
        return ""

    parts: List[str] = [texts[0].rstrip()]
    for text, info in zip(texts[1:], pages_info[1:]):
        stripped = _FM_RE.sub("", text, count=1).lstrip()
        parts.append(f"\n\n<!-- page {info.page} -->\n\n{stripped.rstrip()}")
    return "\n".join(parts) + "\n"
