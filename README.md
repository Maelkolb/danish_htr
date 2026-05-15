# danish_transcriber

A pipeline for transcribing 19th-century Danish handwritten documents
(Kurrentschrift / gotisk skrift) from scanned PDFs into Markdown and
[TEI P5](https://tei-c.org/) XML, with a self-contained HTML viewer for
editorial review.

Uses **Gemini 3.1 Flash-Lite** by default for cost-efficient bulk transcription;
swap in **Gemini 3.1 Pro** for the most difficult pages.

## Pipeline

```
PDF
 ├─ pdf_processor.py      render every page to 400 dpi PNG (PyMuPDF)
 ├─ image_enhancer.py     CLAHE + bilateral filter (faded ink → readable)
 ├─ gemini_client.py      Gemini 3.x call w/ media_resolution_high + thinking
 ├─ transcriber.py        orchestrator → per-page markdown + combined doc
 ├─ tei_converter.py      YAML front-matter + body → TEI P5 XML
 └─ html_generator.py     split-panel review viewer (image | md / TEI)
```

## Installation

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...
```

## Quick start

CLI:

```bash
python run.py letters/1841_letter.pdf --output ./out --thinking medium
```

Python:

```python
from run import run
out = run("letters/1841_letter.pdf", output_dir="./out", thinking="medium")
print(out.html_path)        # open this in a browser
```

Or use the Colab notebook: **`transcribe_colab.ipynb`**.

## Output layout

```
out/<pdf-stem>/
  raw/                            400-dpi page PNGs (unmodified)
  enhanced/                       CLAHE + denoised page PNGs (sent to model)
  transcripts/
    <stem>_page_001.md            per-page markdown w/ YAML front-matter
    ...
  tei/
    <stem>_page_001.xml           per-page TEI P5 XML
    ...
  <stem>.md                       combined markdown
  <stem>.html                     split-panel review viewer
```

## Markdown format

Each transcript starts with YAML front matter the model is prompted to
fill in:

```markdown
---
place: Brøns
date: 1841-03-26
addressee: Herr Pavelsen
sender: ?
language: da
script: kurrent
---

Brøns den 26. Marts 1841.

Höistærede Herr Pavelsen!

Deres … brev har jeg … modtaget …
```

Uncertainty conventions inside the body:

| Marker             | Meaning                              |
|--------------------|--------------------------------------|
| `[ord?]`           | best-guess reading, uncertain        |
| `[...]`            | fully illegible                      |
| `[damage: hole]`   | physical damage obscures text        |
| `[damage: stain]`  | ink blot / water stain               |
| `[damage: tear]`   | torn paper                           |
| `[damage: faded]`  | faded beyond legibility              |

These map to TEI elements `<unclear>`, `<gap reason="illegible"/>`,
`<damage agent="…"/>` in the XML output.

## Tuning

- **Difficult pages**: use `--model gemini-3.1-pro-preview --thinking high`.
- **Token-light bulk runs**: `--thinking low` and
  `--media-resolution media_resolution_medium`.
- **Skip enhancement** when scans are already crisp: `--no-enhance`.

Temperature is intentionally left at Gemini 3's default (1.0) — the
Gemini 3 guide warns that lowering it can cause looping on reasoning
tasks.

## Caveats

The TEI converter is heuristic. Opener / closer detection works well
for typical 19th-c. letter form (dateline + salutation + body +
valediction + signature) but should be reviewed for unusual documents
(deeds, registers, multi-document pages). Treat the XML as a first
draft, not a finished critical edition.
