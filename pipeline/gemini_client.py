"""Gemini 3.x client wrapper for image transcription.

Defaults to ``gemini-3.1-flash-lite`` for cost-efficient bulk work.
For the worst pages, bump ``model`` to ``gemini-3.1-pro-preview`` and
``thinking_level`` to ``"high"``.

Notes on parameters (from the Gemini 3 developer guide):

  * ``media_resolution_high`` (1120 tokens/image) is recommended for
    image analysis where small details matter — handwriting fits.
  * Setting ``media_resolution`` per-Part currently requires the
    ``v1alpha`` API version, which we enable in the client.
  * Temperature should stay at the default (1.0) on Gemini 3 — lower
    values can cause looping/degradation. We do not pass it.
  * Flash-Lite supports thinking_level "minimal" / "low" / "medium" /
    "high". "medium" is a sensible balance for paleography.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types


DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_THINKING = "medium"
DEFAULT_MEDIA_RES = "media_resolution_high"


class GeminiTranscriber:
    """Thin wrapper around ``google-genai`` for single-image transcription."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        thinking_level: str = DEFAULT_THINKING,
        media_resolution: str = DEFAULT_MEDIA_RES,
        max_retries: int = 2,
        retry_backoff_s: float = 4.0,
    ):
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "No API key. Pass api_key=... or set GEMINI_API_KEY env var."
            )

        # v1alpha is required for per-part media_resolution. Even if we ever
        # switch to a global media_resolution it costs nothing to stay on
        # v1alpha for Gemini 3.x features.
        self.client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1alpha"},
        )
        self.model = model
        self.thinking_level = thinking_level
        self.media_resolution = media_resolution
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s

    # ------------------------------------------------------------------ #
    def transcribe_image(
        self,
        image_path: Path | str,
        prompt: str,
        mime_type: Optional[str] = None,
    ) -> str:
        """Send one image + prompt; return the model's text response."""
        image_path = Path(image_path)
        image_bytes = image_path.read_bytes()
        if mime_type is None:
            mime_type = _guess_mime(image_path)

        content = types.Content(
            role="user",
            parts=[
                types.Part(text=prompt),
                types.Part(
                    inline_data=types.Blob(
                        mime_type=mime_type,
                        data=image_bytes,
                    ),
                    media_resolution={"level": self.media_resolution},
                ),
            ],
        )

        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level=self.thinking_level,
            ),
        )

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[content],
                    config=config,
                )
                return _clean_output(response.text or "")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.max_retries:
                    sleep_for = self.retry_backoff_s * (2 ** attempt)
                    time.sleep(sleep_for)
                else:
                    raise

        # Unreachable but appeases the type checker
        raise RuntimeError(f"Transcription failed: {last_exc}")


# ---------------------------------------------------------------------- #
def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/png")


def _clean_output(text: str) -> str:
    """Strip stray markdown code-fences the model sometimes wraps output in.

    The prompt forbids fences, but Gemini occasionally still emits them
    around the whole YAML+body. This is a defensive belt-and-braces strip.
    """
    text = text.strip()
    if text.startswith("```"):
        # drop the opening fence (possibly with language tag) and trailing fence
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    return text
