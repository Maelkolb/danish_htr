"""Convert pipeline markdown (YAML front-matter + body) to TEI P5 XML.

YAML schema (any field may be ``null`` and is then omitted from TEI)::

    place:       str
    date:        str | ISO date
    addressee:   str
    sender:      str
    language:    ISO 639-1 code (default 'da')
    script:      str (default 'kurrent')
    opener:
      dateline:    str   # verbatim text as written on the page
      salutation:  str
    closer:
      valediction: str
      signature:   str

"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from xml.dom import minidom
from xml.etree import ElementTree as ET

import yaml

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

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
    if not isinstance(meta, dict):
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
        if k == "xml_lang":
            el.set(f"{{{XML_NS}}}lang", str(v))
        else:
            el.set(k.replace("_", "-"), str(v))
    return el


def _append_text(parent: ET.Element, text: str) -> None:
    """Append ``text`` either to .text (no children yet) or to last child's .tail."""
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
    """Walk ``text``, converting [bracket markers] into child TEI elements."""
    last = 0
    for m in _BRACKET_RE.finditer(text):
        before = text[last:m.start()]
        if before:
            _append_text(parent, before)
        content = m.group(1).strip()
        parent.append(_marker_to_elem(content))
        last = m.end()

    tail = text[last:]
    if tail:
        _append_text(parent, tail)


def _marker_to_elem(content: str) -> ET.Element:
    """Map one bracket-marker payload to a TEI element.

    Conventions follow TEI P5 ch. 11 (Representation of Primary Sources):
      * Complete loss → ``<gap>`` with @reason and optional @agent
      * Damaged but readable text → ``<damage>`` (not produced here; the
        prompt only emits markers for unreadable spans)
      * Uncertain reading → ``<unclear>`` with @cert
    """
    # [...] / [...] / [. . .]
    if content in {"...", "…", ". . ."}:
        return _elem("gap", reason="illegible")

    # [damage: description] — total loss caused by physical damage.
    # Per TEI, this is <gap reason="damage" agent="…"/>, not <damage/>.
    if content.lower().startswith("damage:"):
        desc = content.split(":", 1)[1].strip()
        agent = desc.split()[0].lower() if desc else "unknown"
        return _elem("gap", reason="damage", agent=agent)

    # [word?] — uncertain reading. cert="low" flags this as machine-tagged.
    if content.endswith("?"):
        return _elem("unclear", text=content[:-1].strip(), cert="low")

    # Fallback: editorial note (e.g. "[cf. fol. 3v]")
    return _elem("note", text=content, type="editorial")


# ---------------------------------------------------------------------- #
# Helpers for nullable string fields
# ---------------------------------------------------------------------- #
def _str_or_none(value) -> Optional[str]:
    """Return ``value`` as a stripped string, or None if empty / null-ish."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {"?", "null", "None"}:
        return None
    return s


def _section(meta: Dict, name: str) -> Dict:
    """Return ``meta[name]`` as a dict, treating non-dict / missing as empty."""
    val = meta.get(name)
    return val if isinstance(val, dict) else {}


# ---------------------------------------------------------------------- #
# Main conversion
# ---------------------------------------------------------------------- #
def markdown_to_tei(
    md: str,
    *,
    source_filename: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Convert one document's markdown (YAML + body) to TEI P5 XML."""
    meta, body = parse_front_matter(md)
    opener_meta = _section(meta, "opener")
    closer_meta = _section(meta, "closer")

    root = _elem("TEI")

    # ── teiHeader ─────────────────────────────────────────────────── #
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
                "Automated transcription produced with Gemini 3."
            ),
        )
    )
    file_desc.append(pub_stmt)

    source_desc = _elem("sourceDesc")
    bibl = _elem("bibl")
    if source_filename:
        bibl.append(_elem("title", text=source_filename))
    if _str_or_none(meta.get("date")):
        date_iso = _iso_date(meta.get("date"))
        bibl.append(_elem("date", text=str(meta["date"]), when=date_iso))
    if _str_or_none(meta.get("place")):
        bibl.append(_elem("placeName", text=str(meta["place"])))
    if len(bibl) == 0:
        bibl.append(_elem("p", text="Manuscript source."))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)

    # profileDesc: language usage + correspDesc
    profile = _elem("profileDesc")
    lang_usage = _elem("langUsage")
    lang_code = str(meta.get("language") or "da")
    lang_usage.append(
        _elem("language", text=_language_label(lang_code), ident=lang_code)
    )
    profile.append(lang_usage)

    sender = _str_or_none(meta.get("sender"))
    addressee = _str_or_none(meta.get("addressee"))
    if sender or addressee:
        corresp = _elem("correspDesc")
        if sender:
            sent = _elem("correspAction", type="sent")
            sent.append(_elem("persName", text=sender))
            place = _str_or_none(meta.get("place"))
            if place:
                sent.append(_elem("placeName", text=place))
            date_iso = _iso_date(meta.get("date"))
            if date_iso:
                sent.append(_elem("date", when=date_iso))
            corresp.append(sent)
        if addressee:
            recv = _elem("correspAction", type="received")
            recv.append(_elem("persName", text=addressee))
            corresp.append(recv)
        profile.append(corresp)

    header.append(profile)
    root.append(header)

    # ── text / body ───────────────────────────────────────────────── #
    text_el = _elem("text")
    body_el = _elem("body")
    div = _elem("div", type="letter")

    # Opener — driven entirely by YAML, never by body inspection.
    opener_el = _build_opener(meta, opener_meta)
    if opener_el is not None:
        div.append(opener_el)

    # Body paragraphs — just split on blank lines.
    body_clean = _strip_page_comments(body).strip()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body_clean) if b.strip()]
    for block in blocks:
        p = _elem("p")
        _process_inline(block, p)
        div.append(p)

    # Closer — also driven entirely by YAML.
    closer_el = _build_closer(closer_meta)
    if closer_el is not None:
        div.append(closer_el)

    body_el.append(div)
    text_el.append(body_el)
    root.append(text_el)

    return _serialize(root)


# ---------------------------------------------------------------------- #
# Opener / closer construction (no heuristics — pure metadata reads)
# ---------------------------------------------------------------------- #
def _build_opener(meta: Dict, opener_meta: Dict) -> Optional[ET.Element]:
    """Build ``<opener>`` from explicit metadata.

    A ``<dateline>`` is emitted if either the verbatim ``opener.dateline``
    is present, or top-level ``place`` / ``date`` are. A ``<salute>`` is
    emitted only if ``opener.salutation`` is present.
    """
    dateline_text = _str_or_none(opener_meta.get("dateline"))
    salute_text = _str_or_none(opener_meta.get("salutation"))
    place = _str_or_none(meta.get("place"))
    date_iso = _iso_date(meta.get("date"))
    has_date_field = _str_or_none(meta.get("date")) is not None

    if not (dateline_text or salute_text or place or has_date_field):
        return None

    opener = _elem("opener")

    if dateline_text or place or has_date_field:
        dateline = _elem("dateline")
        if dateline_text:
            # Verbatim wording from the manuscript; carry the normalised
            # date as a machine-readable child element.
            dateline.text = dateline_text.rstrip(".") + " "
            if date_iso:
                dateline.append(_elem("date", when=date_iso))
        else:
            # No verbatim text — emit structured children only.
            if place:
                dateline.append(_elem("placeName", text=place))
            if has_date_field:
                date_el = _elem("date", text=str(meta["date"]), when=date_iso)
                if len(dateline) > 0:
                    list(dateline)[-1].tail = ", "
                dateline.append(date_el)
        opener.append(dateline)

    if salute_text:
        salute = _elem("salute")
        _process_inline(salute_text, salute)
        opener.append(salute)

    return opener


def _build_closer(closer_meta: Dict) -> Optional[ET.Element]:
    """Build ``<closer>`` from explicit metadata. No heuristics."""
    valediction = _str_or_none(closer_meta.get("valediction"))
    signature = _str_or_none(closer_meta.get("signature"))

    if not (valediction or signature):
        return None

    closer = _elem("closer")
    if valediction:
        salute = _elem("salute")
        _process_inline(valediction, salute)
        closer.append(salute)
    if signature:
        signed = _elem("signed")
        _process_inline(signature, signed)
        closer.append(signed)
    return closer


# ---------------------------------------------------------------------- #
# Small helpers
# ---------------------------------------------------------------------- #
_PAGE_COMMENT_RE = re.compile(r"<!--\s*page\s+\d+\s*-->", re.IGNORECASE)


def _strip_page_comments(text: str) -> str:
    return _PAGE_COMMENT_RE.sub("", text)


def _make_title(meta: Dict) -> str:
    place = _str_or_none(meta.get("place")) or "?"
    date = _str_or_none(meta.get("date")) or "?"
    sender = _str_or_none(meta.get("sender"))
    addressee = _str_or_none(meta.get("addressee"))
    parties: List[str] = []
    if sender:
        parties.append(sender)
    if addressee:
        parties.append(f"to {addressee}")
    parties_str = " ".join(parties)
    if parties_str:
        return f"Letter, {place}, {date} — {parties_str}"
    return f"Letter, {place}, {date}"


def _iso_date(raw) -> Optional[str]:
    """Return an ISO-8601 date string when ``raw`` is parseable, else None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in {"?", "null", "None"}:
        return None
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
    """Pretty-print with XML declaration and a TEI schema processing instruction."""
    rough = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(rough)
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    lines = [ln for ln in pretty.split("\n") if ln.strip()]
    schema_pi = (
        '<?xml-model href="https://tei-c.org/release/xml/tei/custom/schema/'
        'relaxng/tei_all.rng" type="application/xml" '
        'schematypens="http://relaxng.org/ns/structure/1.0"?>'
    )
    return "\n".join([lines[0], schema_pi, *lines[1:]]) + "\n"
