"""Danish handwritten document transcription pipeline.

Components:
    pdf_processor   — PDF → per-page PNG renderings
    image_enhancer  — contrast / denoise for faded ink
    gemini_client   — wrapper around google-genai for Gemini 3.x
    prompts         — system prompts (Kurrent / 19th-c. Danish)
    transcriber     — end-to-end orchestration
    tei_converter   — Markdown front-matter + body → TEI P5 XML
    html_generator  — split-panel review viewer (image | md / tei)
"""

from .transcriber import DocumentTranscriber
from .gemini_client import GeminiTranscriber
from .tei_converter import markdown_to_tei
from .html_generator import generate_html

__all__ = [
    "DocumentTranscriber",
    "GeminiTranscriber",
    "markdown_to_tei",
    "generate_html",
]
