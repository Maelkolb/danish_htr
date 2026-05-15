"""Convert pipeline markdown (YAML front-matter + body) to TEI P5 XML.

The output follows TEI's correspondence customisation as closely as a
heuristic converter reasonably can:

    <TEI>
      <teiHeader>
        <fileDesc>
          <titleStmt><title/></titleStmt>
          <publicationStmt><p/></publicationStmt>
          <sourceDesc><bibl>…</bibl></sourceDesc>
        </fileDesc>
        <profileDesc>
          <langUsage><language/></langUsage>
          <correspDesc>
            <correspAction type="sent"><persName/><placeName/><date/></correspAction>
            <correspAction type="received"><persName/></correspAction>
          </correspDesc>
        </profileDesc>
      </teiHeader>
      <text>
        <body>
          <div type="letter">
            <opener>
              <dateline>…</dateline>
              <salute>…</salute>
            </opener>
            <p>…</p>
            <closer>
              <salute>…</salute>
              <signed>…</signed>
            </closer>
          </div>
        </body>
      </text>
    </TEI>

Inline bracket markers from the prompt are mapped to TEI elements:

    [word?]            -> <unclear>word</unclear>
    [...]              -> <gap reason="illegible"/>
    [damage: hole]     -> <damage agent="hole"/>
    anything else      -> <note type="editorial">…</note>

The converter is heuristic — it should be treated as a first draft for
editor review, not a finished critical edition.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from xml.dom import minidom
from xml.etree import ElementTree as ET

import yaml

TEI_NS = "http://www.tei-c.org/ns/1.0"

# Register so ET writes xmlns="…" rather than ns0: prefixes.
ET.register_namespace("", TEI_NS)


# ---------------------------------------------------------------------- #
# Front-matter parsing
# ---------------------------------------------------------------------- #
_FM_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)


def parse_front_matter(md: str) -> Tuple[Dict, str]:
    """Return (metadata-dict, body-text). Metadata may be empty."""
    m = _FM_RE.match(md)
    if not m:
        return {}, md
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, m.group(2)


# ---------------------------------------------------------------------- #
# Element factories
# ---------------------------------------------------------------------- #
def _elem(tag: str, text: Optional[str] = None, **attrs) -> ET.Element:
    el = ET.Element(f"{{{TEI_NS}}}{tag}")
    if text is not None:
        el.text = text
    for k, v in attrs.items():
        if v is None:
            continue
        # Allow "xml_lang" → "xml:lang"; otherwise underscores → hyphens
        if k == "xml_lang":
            el.set("{http://www.w3.org/XML/1998/namespace}lang", str(v))
        else:
            el.set(k.replace("_", "-"), str(v))
    return el


def _append_text(parent: ET.Element, text: str) -> None:
    """Append `text` either to .text (no children yet) or to last child's .tail."""
    if len(parent) == 0:
        parent.text = (parent.text or "") + text
    else:
        last = list(parent)[-1]
        last.tail = (last.tail or "") + text


# ---------------------------------------------------------------------- #
# Inline bracket markers → TEI elements
# ---------------------------------------------------------------------- #
_BRACKET_RE = re.compile(r"\[([^\]]+)\]")


def _process_inline(text: str, parent: ET.Element) -> None:
    """Walk `text`, converting [bracket markers] into child TEI elements."""
    last = 0
    for m in _BRACKET_RE.finditer(text):
        before = text[last : m.start()]
        if before:
            _append_text(parent, before)

        content = m.group(1).strip()
        parent.append(_marker_to_elem(content))
        last = m.end()

    tail = text[last:]
    if tail:
        _append_text(parent, tail)


def _marker_to_elem(content: str) -> ET.Element:
    """Map one bracket-marker payload to a TEI element."""
    # [...] or […]
    if content in {"...", "…", ". . ."}:
        return _elem("gap", reason="illegible")

    # [damage: description]
    if content.lower().startswith("damage:"):
        desc = content.split(":", 1)[1].strip()
        agent = desc.split()[0].lower() if desc else "unknown"
        return _elem("damage", agent=agent)

    # [word?] — uncertain reading
    if content.endswith("?"):
        return _elem("unclear", text=content[:-1].strip(), reason="illegible")

    # Fallback: editorial note
    return _elem("note", text=content, type="editorial")


# ---------------------------------------------------------------------- #
# Opener / closer heuristics
# ---------------------------------------------------------------------- #
# Common 19th-c. Danish valediction tokens. Keep the list short — false
# positives are worse than missing the closer (the body still wraps in <p>).
_VALEDICTION_RE = re.compile(
    r"\b("
    r"ærbødig|ærbødigst|underdanig|underdanigst|"
    r"hengiven|kjærligst|venligst|"
    r"Deres\s+(ærbødige|hengivne|tro)"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_closer(block: str, is_last: bool, sender: Optional[str]) -> bool:
    """A block is a closer only if it actually contains a valediction or
    the known sender name. The 'short final paragraph' heuristic produces
    too many false positives on documents without explicit valedictions
    (deeds, registers, prose fragments)."""
    if not is_last:
        return False
    if _VALEDICTION_RE.search(block):
        return True
    if sender:
        s = str(sender).strip()
        if s and s != "?" and s in block:
            return True
    return False


# ---------------------------------------------------------------------- #
# Main conversion
# ---------------------------------------------------------------------- #
def markdown_to_tei(
    md: str,
    *,
    source_filename: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Convert one letter's markdown (YAML + body) to TEI P5 XML."""
    meta, body = parse_front_matter(md)

    root = _elem("TEI")

    # ── teiHeader ──────────────────────────────────────────────────── #
    header = _elem("teiHeader")
    file_desc = _elem("fileDesc")

    title_text = title or _make_title(meta)
    title_stmt = _elem("titleStmt")
    title_stmt.append(_elem("title", text=title_text))
    file_desc.append(title_stmt)

    pub_stmt = _elem("publicationStmt")
    pub_stmt.append(
        _elem(
            "p",
            text=(
                "Automated transcription produced with Gemini 3 and reviewed "
                "by an editor."
            ),
        )
    )
    file_desc.append(pub_stmt)

    source_desc = _elem("sourceDesc")
    bibl = _elem("bibl")
    if source_filename:
        bibl.append(_elem("title", text=source_filename))
    if meta.get("date"):
        date_iso = _iso_date(meta["date"])
        bibl.append(_elem("date", text=str(meta["date"]), when=date_iso))
    if meta.get("place"):
        bibl.append(_elem("placeName", text=str(meta["place"])))
    if len(bibl) == 0:
        bibl.append(_elem("p", text="Manuscript source."))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)

    # profileDesc: language + correspondence action(s)
    profile = _elem("profileDesc")
    lang_usage = _elem("langUsage")
    lang_code = str(meta.get("language", "da"))
    lang_usage.append(
        _elem("language", text=_language_label(lang_code), ident=lang_code)
    )
    profile.append(lang_usage)

    if meta.get("sender") or meta.get("addressee"):
        corresp = _elem("correspDesc")
        if meta.get("sender") and str(meta["sender"]).strip() not in {"", "?"}:
            sent = _elem("correspAction", type="sent")
            sent.append(_elem("persName", text=str(meta["sender"])))
            if meta.get("place"):
                sent.append(_elem("placeName", text=str(meta["place"])))
            if meta.get("date"):
                sent.append(_elem("date", when=_iso_date(meta["date"])))
            corresp.append(sent)
        if meta.get("addressee") and str(meta["addressee"]).strip() not in {"", "?"}:
            recv = _elem("correspAction", type="received")
            recv.append(_elem("persName", text=str(meta["addressee"])))
            corresp.append(recv)
        if len(corresp) > 0:
            profile.append(corresp)

    header.append(profile)
    root.append(header)

    # ── text / body ───────────────────────────────────────────────── #
    text_el = _elem("text")
    body_el = _elem("body")
    letter = _elem("div", type="letter")

    body_clean = _strip_page_comments(body).strip()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body_clean) if b.strip()]

    if not blocks:
        body_el.append(letter)
        text_el.append(body_el)
        root.append(text_el)
        return _serialize(root)

    # Detect closer
    closer_block: Optional[str] = None
    if len(blocks) > 1 and _looks_like_closer(
        blocks[-1], is_last=True, sender=meta.get("sender")
    ):
        closer_block = blocks.pop()

    # Build opener from metadata (always emitted if we have date or place)
    opener = _build_opener(meta, blocks)
    if opener is not None:
        letter.append(opener)

    # Body paragraphs
    for block in blocks:
        p = _elem("p")
        _process_inline(block, p)
        letter.append(p)

    # Closer
    if closer_block is not None:
        letter.append(_build_closer(closer_block, meta))

    body_el.append(letter)
    text_el.append(body_el)
    root.append(text_el)

    return _serialize(root)


# ---------------------------------------------------------------------- #
# Opener / closer construction
# ---------------------------------------------------------------------- #
def _build_opener(meta: Dict, blocks: List[str]) -> Optional[ET.Element]:
    """Build <opener> with <dateline> + optional <salute>.

    Heuristic:
      * If the first block is a short textual date line (contains a year
        and/or the place name from metadata), consume it as the dateline's
        visible text.
      * If the next block looks like a salutation, pull it as <salute>.
      * Otherwise leave both as ordinary <p>s.
    """
    has_metadata_dateline = bool(meta.get("place") or meta.get("date"))

    # Step 1: detect a textual dateline as the first block.
    textual_dateline: Optional[str] = None
    if blocks and _looks_like_textual_dateline(blocks[0], meta):
        textual_dateline = blocks.pop(0)

    # Step 2: detect the salute as the (now) first block.
    salute_block: Optional[str] = None
    if blocks and _looks_like_salute(blocks[0]):
        salute_block = blocks.pop(0)

    if not has_metadata_dateline and textual_dateline is None and salute_block is None:
        return None

    opener = _elem("opener")

    # Build <dateline>. If we have a textual dateline, use it as the
    # visible text and add a structured <date> child carrying the
    # normalised @when value; otherwise emit structured children only.
    if has_metadata_dateline or textual_dateline:
        dateline = _elem("dateline")
        if textual_dateline:
            dateline.text = textual_dateline.rstrip(".") + " "
            iso = _iso_date(meta.get("date"))
            if iso:
                # An empty <date when="…"/> alongside the textual content
                # makes the normalised date machine-readable.
                dateline.append(_elem("date", when=iso))
        else:
            if meta.get("place"):
                dateline.append(_elem("placeName", text=str(meta["place"])))
            if meta.get("date"):
                iso = _iso_date(meta["date"])
                date_el = _elem("date", text=str(meta["date"]), when=iso)
                if len(dateline) > 0:
                    list(dateline)[-1].tail = ", "
                dateline.append(date_el)
        opener.append(dateline)

    if salute_block is not None:
        salute = _elem("salute")
        _process_inline(salute_block, salute)
        opener.append(salute)

    return opener


def _looks_like_textual_dateline(block: str, meta: Dict) -> bool:
    """Detect a redundant textual dateline like 'Brøns den 26. Marts 1841.'"""
    if "\n" in block.strip():
        return False
    stripped = block.strip()
    if len(stripped) > 100:
        return False
    has_year = bool(re.search(r"\b1[78]\d{2}\b", stripped))
    place = str(meta.get("place") or "").strip()
    has_place = bool(place) and place != "?" and place.lower() in stripped.lower()
    return has_year or has_place


def _looks_like_salute(block: str) -> bool:
    """First-block salutation heuristic."""
    if "\n" in block.strip():
        return False  # multiline → probably a body paragraph
    stripped = block.strip()
    if len(stripped) > 80:
        return False
    if stripped.endswith(("!", ",")):
        return True
    # Common Danish salutation openers
    if re.match(
        r"^(Höistærede|Højærede|Højtærede|Kjære|Kære|Hr\.|Herr)\b",
        stripped,
    ):
        return True
    return False


def _build_closer(block: str, meta: Dict) -> ET.Element:
    """Split a closer block into <salute> and <signed> lines."""
    closer = _elem("closer")
    sender_name = str(meta.get("sender", "")).strip()
    lines = [ln.strip() for ln in block.split("\n") if ln.strip()]

    # Last line is typically the signature; preceding lines are the salute
    signed_idx = len(lines) - 1
    if sender_name and sender_name != "?":
        for i, ln in enumerate(lines):
            if sender_name in ln:
                signed_idx = i
                break

    salute_lines = lines[:signed_idx]
    signed_line = lines[signed_idx] if 0 <= signed_idx < len(lines) else None

    if salute_lines:
        salute = _elem("salute")
        _process_inline(" ".join(salute_lines), salute)
        closer.append(salute)
    if signed_line:
        signed = _elem("signed")
        _process_inline(signed_line, signed)
        closer.append(signed)

    return closer


# ---------------------------------------------------------------------- #
# Small helpers
# ---------------------------------------------------------------------- #
_PAGE_COMMENT_RE = re.compile(r"<!--\s*page\s+\d+\s*-->", re.IGNORECASE)


def _strip_page_comments(text: str) -> str:
    return _PAGE_COMMENT_RE.sub("", text)


def _make_title(meta: Dict) -> str:
    place = meta.get("place") or "?"
    date = meta.get("date") or "?"
    sender = meta.get("sender")
    addressee = meta.get("addressee")
    parties = []
    if sender and sender != "?":
        parties.append(str(sender))
    if addressee and addressee != "?":
        parties.append(f"to {addressee}")
    parties_str = " ".join(parties)
    if parties_str:
        return f"Letter, {place}, {date} — {parties_str}"
    return f"Letter, {place}, {date}"


def _iso_date(raw) -> Optional[str]:
    """Return an ISO-8601 date string when ``raw`` is parseable, else None.

    Accepts date objects, datetimes, "YYYY-MM-DD" strings, or "?".
    Leaves anything else as None (the original string still ends up in
    the element body via the ``text`` argument).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "?":
        return None
    # Already ISO?
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{4}", s):
        return s
    return None


def _language_label(code: str) -> str:
    return {
        "da": "Danish",
        "de": "German",
        "no": "Norwegian",
        "sv": "Swedish",
        "en": "English",
        "la": "Latin",
        "fr": "French",
    }.get(code.lower(), code)


def _serialize(root: ET.Element) -> str:
    """Pretty-print the TEI document with an XML declaration and TEI schema PI."""
    rough = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(rough)
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    # minidom inserts blank lines; drop them
    lines = [ln for ln in pretty.split("\n") if ln.strip()]
    # The first line is the XML declaration produced by minidom; insert the
    # TEI schema processing instruction after it for clean validation.
    schema_pi = (
        '<?xml-model href="https://tei-c.org/release/xml/tei/custom/schema/'
        'relaxng/tei_all.rng" type="application/xml" '
        'schematypens="http://relaxng.org/ns/structure/1.0"?>'
    )
    return "\n".join([lines[0], schema_pi, *lines[1:]]) + "\n"
