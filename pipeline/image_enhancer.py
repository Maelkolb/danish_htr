"""Image enhancement for scanned handwritten documents.

The goal is not to make pages look pretty for human eyes — it's to make
faded ink, foxing, and stained paper easier for a vision model to read.

We deliberately stay conservative:

  * Grayscale conversion preserves stroke shape and discards colour noise
    from yellowed paper.
  * CLAHE (contrast-limited adaptive histogram equalisation) pulls faded
    ink back out of the background without globally over-darkening stains.
  * A small bilateral filter smooths the paper while keeping ink edges
    sharp — Gaussian or median blurs erode thin strokes.
  * Optional mild unsharp mask sharpens after denoising.

Aggressive thresholding (Otsu, Sauvola, etc.) is intentionally avoided —
it tends to drop the lightest strokes entirely, which is exactly the
information we want to keep on 19th-c. iron-gall-ink pages.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def enhance_image(
    input_path: Path | str,
    output_path: Path | str,
    *,
    apply_clahe: bool = True,
    clahe_clip: float = 2.5,
    clahe_tile: int = 8,
    denoise: bool = True,
    sharpen: bool = False,
    max_dim: Optional[int] = 2400,
) -> Path:
    """Enhance contrast and clarity of one scanned document image.

    Parameters
    ----------
    input_path, output_path : path-like
    apply_clahe : bool
        Run adaptive histogram equalisation. Almost always helpful on
        faded ink; turn off only if the source is already crisp.
    clahe_clip : float
        CLAHE clip limit. 2.0–3.0 is a good range; higher amplifies noise.
    clahe_tile : int
        Tile grid size (square). 8 means an 8×8 grid of local tiles.
    denoise : bool
        Bilateral filter pass. Slow on huge images but worth it.
    sharpen : bool
        Optional unsharp mask. Use on smooth scans; can amplify foxing
        on noisy ones.
    max_dim : int | None
        If given, downscale so the longer side is at most this many
        pixels. Gemini caps per-image tokens (1120 at media_resolution_high)
        regardless of input size, so very large scans waste IO without
        improving model accuracy.

    Returns the output path.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    img = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {input_path}")

    # Downscale enormous scans
    if max_dim is not None:
        h, w = img.shape
        longest = max(h, w)
        if longest > max_dim:
            scale = max_dim / longest
            new_size = (int(round(w * scale)), int(round(h * scale)))
            img = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)

    if apply_clahe:
        clahe = cv2.createCLAHE(
            clipLimit=clahe_clip,
            tileGridSize=(clahe_tile, clahe_tile),
        )
        img = clahe.apply(img)

    if denoise:
        # Bilateral preserves edges (strokes) while smoothing flat regions
        # (paper). Keep d small (5) for speed; sigmas around 50 give a
        # gentle effect that doesn't erode hairlines.
        img = cv2.bilateralFilter(img, d=5, sigmaColor=50, sigmaSpace=50)

    if sharpen:
        blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=1.5)
        img = cv2.addWeighted(img, 1.5, blurred, -0.5, 0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    return output_path


def make_side_by_side(
    raw_path: Path | str,
    enhanced_path: Path | str,
    output_path: Path | str,
) -> Path:
    """Build a debug image: raw on the left, enhanced on the right.

    Useful for tuning CLAHE / denoise parameters interactively.
    """
    raw = cv2.imread(str(raw_path), cv2.IMREAD_GRAYSCALE)
    enh = cv2.imread(str(enhanced_path), cv2.IMREAD_GRAYSCALE)
    if raw.shape != enh.shape:
        enh = cv2.resize(enh, (raw.shape[1], raw.shape[0]))
    combined = np.hstack([raw, enh])
    output_path = Path(output_path)
    cv2.imwrite(str(output_path), combined)
    return output_path
