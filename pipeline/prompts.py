"""Prompts for the transcription model.

Kept in a separate module so they can be edited and version-controlled
independently of the Python plumbing.
"""

# Main per-page transcription prompt.
#
# Design notes:
#   * Anchored in a clear expert persona (paleographer) — Gemini 3 follows
#     concise direct instructions better than verbose role-play.
#   * Explicit uncertainty markers prevent confident hallucination, which
#     is the #1 failure mode on damaged Kurrent pages.
#   * YAML front matter is requested so the downstream TEI converter can
#     extract structured metadata deterministically.
#   * Output format is fully specified — no commentary, no markdown
#     fences around the YAML.
TRANSCRIPTION_PROMPT = """\
You are an expert paleographer specialising in 19th-century Danish handwriting,
particularly Gothic cursive script (gotisk skrift / Kurrentschrift). You are
looking at a scanned page of a Danish manuscript, most likely a letter or an
official document from c. 1820–1880.

Transcribe everything you can read on the page. Apply these rules strictly:

1. ACCURACY OVER COMPLETENESS. If a word is uncertain, write your best guess
   followed by a question mark in brackets, e.g. [Pavelsen?]. If a word or
   passage is fully illegible, mark it [...]. NEVER invent text to fill gaps.

2. PRESERVE ORIGINAL ORTHOGRAPHY. Keep 19th-century spelling exactly (e.g.
   "Höistærede", "kjøbe", "saa", "Tilstand"), the convention of capitalising
   nouns, and the original punctuation. Do not modernise.

3. MARK PHYSICAL DAMAGE with bracketed notes:
       [damage: hole]      — punch-hole or burn-through
       [damage: tear]      — torn paper
       [damage: stain]     — ink blot or water stain obscuring text
       [damage: faded]     — text too faded to read
   Use these only where damage actually prevents reading.

4. MIXED SCRIPTS. 19th-c. Danish letters often use Gothic cursive for Danish
   words and Latin/italic script for foreign words, proper names, place names,
   and amounts. Transcribe both faithfully; no special marker is needed.

5. OUTPUT FORMAT. Produce UTF-8 markdown with a YAML front-matter block
   followed by the body. No commentary, no code fences, no preamble.

   ---
   place: <place named at top of letter, or "?">
   date: <ISO YYYY-MM-DD if discernible, else the original form>
   addressee: <name/title of recipient if discernible, else "?">
   sender: <signature if visible, else "?">
   language: da
   script: kurrent
   ---

   <Place>, <Date written out>

   <Salutation, e.g. "Höistærede Herr Pavelsen!">

   <Body paragraph 1.>

   <Body paragraph 2.>
   ...

   <Closing valediction, e.g. "Deres ærbødige">
   <Signature>

6. Paragraphs are separated by a single blank line. Preserve manuscript line
   breaks only inside lists, addresses, or verse — collapse them into prose
   for ordinary running text.
"""


# Optional second-pass prompt if a page is particularly degraded.
# Currently unused by the default pipeline but available for callers
# that want to retry difficult pages with a stronger model.
RETRY_PROMPT_SUFFIX = """\

This page is particularly damaged. Please be especially conservative:
mark all but the most clearly legible words as uncertain, and do not
attempt to reconstruct phrases from context alone.
"""
