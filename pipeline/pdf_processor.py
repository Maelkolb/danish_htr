"""Render each page of a PDF to a high-DPI PNG.

We use PyMuPDF (fitz) rather than pdf2image because it doesn't need a
poppler system install — useful in Colab. 400 dpi is a good default for
handwriting: enough to resolve fine pen strokes without exploding file size.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import fitz  # PyMuPDF


def pdf_to_images(
    pdf_path: Path | str,
    output_dir: Path | str,
    dpi: int = 400,
) -> List[Path]:
    """Render every page of ``pdf_path`` to a PNG in ``output_dir``.

    Returns the list of generated image paths in page order.
    Output filenames are ``{stem}_page_{NNN}.png`` (1-indexed, zero-padded).
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = pdf_path.stem
    zoom = dpi / 72.0  # PDF default user-space resolution is 72 dpi
    matrix = fitz.Matrix(zoom, zoom)

    image_paths: List[Path] = []
    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out_path = output_dir / f"{stem}_page_{page_index:03d}.png"
            pix.save(out_path)
            image_paths.append(out_path)

    return image_paths


def count_pages(pdf_path: Path | str) -> int:
    """Return the number of pages without rendering anything."""
    with fitz.open(pdf_path) as doc:
        return doc.page_count
