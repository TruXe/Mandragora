"""Copy domain: UI microcopy and marketing or documentation prose.

Inputs: Markdown (.md/.mdx), plain text, HTML (text extracted per element) and
JSON string tables (UI string files, with --domain copy). Code is not prose:
fenced blocks, inline code spans, HTML comments and link targets are removed
before any rule runs, so documentation can quote slop phrases inside
backticks without tripping the scanner.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from scanners.core import hit, is_emoji, read_text, register_domain, rule

DOMAIN = "copy"
EXTENSIONS = (".md", ".mdx", ".markdown", ".txt", ".rst")

# ---------------------------------------------------------------- thresholds
# Emoji-led bullets before they count as a list style rather than one accent.
EMOJI_BULLET_MIN = 2
# Title Case: a heading needs this many capitalizable words after the first
# word to be judged, and this many title-cased headings must exist.
TITLE_MIN_MAJOR_WORDS = 3
TITLE_MIN_HEADINGS = 2
TITLE_MIN_RATIO = 0.5
# Plain text: a one-line paragraph up to this many words without end
# punctuation is treated as a heading.
TXT_HEADING_MAX_WORDS = 10
# Rule of three: at least this many of the three items must be filler words.
TRIAD_MIN_FILLER = 2

HYPE_RE = re.compile(
    r"\b(elevat(?:e|es|ed|ing)|seamless(?:ly)?|unlock(?:s|ed|ing)?|supercharg(?:e|es|ed|ing)|"
    r"empower(?:s|ed|ing|ment)?|leverag(?:e|es|ed|ing)|unleash(?:es|ed|ing)?|"
    r"revolutioni[sz](?:e|es|ed|ing)|game[- ]chang(?:er|ing)|next[- ]level|delv(?:e|es|ing)|"
    r"tapestry|effortless(?:ly)?|streamlin(?:e|es|ed|ing)|transformative|synerg(?:y|ies)|"
    r"holistic|paradigm shift|groundbreaking|reimagin(?:e|es|ed|ing)|embark(?:s|ed|ing)?|"
    r"testament to|in the realm of|harness(?:es|ing)? the power)\b", re.I)
SUPERLATIVE_RE = re.compile(
    r"\b(best[- ]in[- ]class|world[- ]class|industry[- ]leading|unparalleled|unmatched|"
    r"second to none|the ultimate|lightning[- ]fast|blazing(?:ly)?[- ]fast|cutting[- ]edge|"
    r"state[- ]of[- ]the[- ]art|unrivaled|unrivalled|top[- ]notch|incredibly powerful|"
    r"truly (?:unique|remarkable|exceptional)|like never before)\b", re.I)
OPENER_RE = re.compile(
    r"\b(in today'?s (?:(?:fast[- ]paced|digital|modern|ever[- ](?:changing|evolving)|"
    r"rapidly (?:changing|evolving)|competitive|hyper[- ]connected|busy)[ ,]+){1,2}"
    r"(?:world|age|landscape|era|environment|market)|"
    r"in an ever[- ](?:changing|evolving) (?:world|landscape)|in the modern era|"
    r"now more than ever|in this day and age)\b", re.I)
NEGATIVE_PARALLEL_RE = re.compile(
    r"\bnot (?:just|only|merely|simply) (?:about )?[^.;!?]{1,80}?,?\s*but\b|"
    r"\b(?:isn'?t|aren'?t|is not|are not|wasn'?t) (?:just|only|merely) [^.;!?]{1,60}[,;.]\s*"
    r"(?:it'?s|they'?re|it is|this is)\b|"
    r"\bit'?s not (?:just |only |about )?[^.;!?]{1,50}[,.;]\s*it'?s\b|"
    r"\bmore than just\b|\bno longer just\b", re.I)
WHETHER_RE = re.compile(r"\bwhether you(?:'re| are)\b[^.?!]{1,80}?\bor\b", re.I)
CLOSING_RE = re.compile(
    r"\b(ready to (?:get started|dive in|take [^.?!]{1,40}|transform [^.?!]{1,40}|level up)\??|"
    r"get started today|what are you waiting for|don'?t miss out|join thousands of|"
    r"let me know if you(?:'d| would) like|feel free to (?:reach out|ask|contact)|"
    r"i hope this helps|happy coding)\b", re.I)
SYCOPHANT_RE = re.compile(
    r"^\W*(great question|excellent question|absolutely|certainly|of course|"
    r"i'?d be (?:happy|glad|delighted) to help|sure thing)\b[!,.]", re.I)
REVEAL_RE = re.compile(
    r"\bthe (result|answer|secret|best part|catch|kicker|truth|twist|outcome|bottom line)\?",
    re.I)
EM_DASH = "—"
EN_DASH = "–"
DASH_RE = re.compile("—|(?<=[A-Za-z0-9,.)'\"]) [-–] (?=[A-Za-z0-9('\"])|"
                     r"(?<=[A-Za-z]) -- (?=[A-Za-z])|(?<=[A-Za-z])--(?=[A-Za-z])")
FILLER_WORDS = set("""
    fast faster simple simpler easy easier powerful secure scalable reliable beautiful intuitive
    flexible efficient modern elegant smart smarter seamless robust innovative effortless sleek
    stunning lightweight blazing better stronger clean cleaner delightful affordable
    customizable performant productive creative engaging dynamic versatile comprehensive
    speed simplicity power clarity confidence creativity productivity innovation growth
    efficiency flexibility scale security reliability performance control freedom peace
    joy ease magic style quality
""".split())
TRIAD_RE = re.compile(r"\b([A-Za-z]+),\s+([A-Za-z]+),?\s+(?:and|&)\s+([A-Za-z]+)\b")
FRAGMENT_TRIAD_RE = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-z]+)\.\s+([A-Z][a-z]+)\.\s+([A-Z][a-z]+)\.")
MINOR_WORDS = set("a an the and or but nor for so yet of on in to at by with vs via as per from "
                  "into onto over is are be".split())


@dataclass
class Segment:
    line: int
    kind: str     # heading, bullet, para, cell, cta
    text: str     # cleaned prose
    raw: str      # original first line (emoji and markers kept)


@dataclass
class CopyDoc:
    path: Path
    segments: list


INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")
LINK_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|\[([^\]]+)\]\([^)]*\)")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _clean(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'")
    s = INLINE_CODE_RE.sub("code", s)
    s = LINK_RE.sub(lambda m: m.group(1) or "", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"(\*\*|__|\*|_)(\S[^*_]*?\S|\S)\1", r"\2", s)
    return " ".join(s.split())


def parse_markdown(text: str) -> list:
    text = COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines = text.split("\n")
    segs, para, para_start, para_raw = [], [], 0, ""
    fence = None
    i = 0

    def flush():
        nonlocal para
        if para:
            segs.append(Segment(para_start, "para", _clean(" ".join(para)), para_raw))
            para = []

    if lines and lines[0].strip() == "---":
        end = next((j for j in range(1, len(lines)) if lines[j].strip() == "---"), None)
        if end is not None:
            for j in range(1, end):
                m = re.match(r"^description:\s*(.+)$", lines[j])
                if m:
                    segs.append(Segment(j + 1, "para", _clean(m.group(1).strip("\"'")), lines[j]))
            i = end + 1
    while i < len(lines):
        line, n = lines[i], i + 1
        stripped = line.strip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            i += 1
            continue
        m = re.match(r"^\s*(```+|~~~+)", line)
        if m:
            flush()
            fence = m.group(1)[:3]
            i += 1
            continue
        if not stripped:
            flush()
        elif re.match(r"^#{1,6}\s", stripped):
            flush()
            segs.append(Segment(n, "heading", _clean(stripped.lstrip("#").strip()), line))
        elif re.match(r"^\s*([-*+]|\d+[.)])\s+", line):
            flush()
            body = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", line)
            segs.append(Segment(n, "bullet", _clean(body), line))
        elif stripped.startswith("|"):
            flush()
            if not re.fullmatch(r"\|?[\s:|-]+\|?", stripped):
                for cell in stripped.strip("|").split("|"):
                    if cell.strip():
                        segs.append(Segment(n, "cell", _clean(cell), cell))
        elif re.fullmatch(r"[-=*_]{3,}", stripped):
            flush()
        else:
            body = stripped.lstrip(">").strip()
            if not para:
                para_start, para_raw = n, line
            para.append(body)
        i += 1
    flush()
    return segs


def parse_plain(text: str) -> list:
    segs = []
    blocks, cur, start = [], [], 1
    for n, line in enumerate(text.split("\n"), 1):
        if line.strip():
            if not cur:
                start = n
            cur.append(line)
        elif cur:
            blocks.append((start, cur))
            cur = []
    if cur:
        blocks.append((start, cur))
    for start, block in blocks:
        bullets = [l for l in block if re.match(r"^\s*([-*+•]|\d+[.)])\s+", l) or
                   (l.strip() and is_emoji(l.strip()[0]))]
        if bullets and len(bullets) == len(block):
            for k, l in enumerate(block):
                body = re.sub(r"^\s*([-*+•]|\d+[.)])\s+", "", l)
                segs.append(Segment(start + k, "bullet", _clean(body), l))
            continue
        joined = " ".join(l.strip() for l in block)
        words = joined.split()
        if len(block) == 1 and len(words) <= TXT_HEADING_MAX_WORDS and \
                not re.search(r"[.!?:,;]$", joined):
            segs.append(Segment(start, "heading", _clean(joined), block[0]))
        else:
            segs.append(Segment(start, "para", _clean(joined), block[0]))
    return segs


TEXT_TAGS = {"p": "para", "li": "bullet", "button": "cta", "a": "cta", "td": "cell", "th": "cell",
             "label": "para", "span": "para", "blockquote": "para", "figcaption": "para",
             "dd": "para", "dt": "para", "small": "para", "div": "para"}


def parse_html(text: str, path: Path) -> list:
    from scanners import scan_web

    doc = scan_web.parse_web(text, path)
    segs = []
    for node in doc.nodes():
        if node.tag in ("script", "style"):
            continue
        own = node.own_text()
        if not own:
            continue
        if node.tag in scan_web.HEADING_TAGS:
            segs.append(Segment(node.line, "heading", _clean(node.text()), node.text()))
        elif node.tag in TEXT_TAGS:
            segs.append(Segment(node.line, TEXT_TAGS[node.tag], _clean(own), own))
    return segs


def parse_json_strings(text: str) -> list:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_plain(text)
    segs = []

    def walk(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str) and value.strip():
            kind = "heading" if re.search(r"title|heading|header", key, re.I) else "para"
            line = 1 + text[: max(0, text.find(json.dumps(value)[1:-1]))].count("\n")
            segs.append(Segment(line, kind, _clean(value), value))

    walk(data)
    return segs


def parse_copy(text: str, path: Path | None = None) -> CopyDoc:
    path = path or Path("inline.md")
    ext = path.suffix.lower()
    if ext in (".md", ".mdx", ".markdown", ".rst"):
        segs = parse_markdown(text)
    elif ext in (".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro") or \
            path.name.lower().endswith(".blade.php"):
        segs = parse_html(text, path)
    elif ext == ".json":
        segs = parse_json_strings(text)
    else:
        segs = parse_plain(text)
    return CopyDoc(path, segs)


def load(path: Path) -> CopyDoc:
    return parse_copy(read_text(path), path)


def sniff(path: Path, head: bytes) -> int:
    ext = path.suffix.lower()
    if ext in (".md", ".mdx", ".markdown", ".rst"):
        return 70
    if ext == ".txt":
        return 50
    return 0


register_domain(DOMAIN, load=load, sniff=sniff, extensions=EXTENSIONS,
                description="UI microcopy, marketing and documentation prose")


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def _scan(doc: CopyDoc, pattern, conf=0.85, kinds=None, limit=20):
    n = 0
    for seg in doc.segments:
        if kinds and seg.kind not in kinds:
            continue
        for m in pattern.finditer(seg.text):
            n += 1
            if n > limit:
                return
            yield hit(f"line {seg.line}", f"'{m.group(0)}' in: {seg.text[:80]}", conf)


@rule("copy.hype-words", recognition="copy-hype-vocabulary", severity=4)
def r_hype(doc: CopyDoc):
    """Stock hype verbs and adjectives (elevate, seamless, unlock, supercharge)."""
    yield from _scan(doc, HYPE_RE, 0.8)


@rule("copy.dash-connector", recognition="copy-dash-connector", severity=3)
def r_dash(doc: CopyDoc):
    """Em dash or spaced hyphen used to join clauses."""
    n = 0
    for seg in doc.segments:
        if seg.kind == "cell" and seg.text.strip() in ("-", EN_DASH, EM_DASH):
            continue
        for m in DASH_RE.finditer(seg.text):
            n += 1
            if n > 20:
                return
            mark = "em dash" if m.group(0) == EM_DASH else "spaced dash"
            ctx = seg.text[max(0, m.start() - 30): m.end() + 30]
            yield hit(f"line {seg.line}", f"{mark}: ...{ctx}...", 0.8)


@rule("copy.rule-of-three", recognition="copy-rule-of-three", severity=3)
def r_triad(doc: CopyDoc):
    """Three stacked filler adjectives or one-word sentences."""
    for seg in doc.segments:
        for m in TRIAD_RE.finditer(seg.text):
            words = [w.lower() for w in m.groups()]
            if sum(1 for w in words if w in FILLER_WORDS) >= TRIAD_MIN_FILLER:
                yield hit(f"line {seg.line}", f"triad '{m.group(0)}'", 0.8)
        for m in FRAGMENT_TRIAD_RE.finditer(seg.text):
            yield hit(f"line {seg.line}", f"fragment triad '{' '.join(m.groups())}'", 0.85)


@rule("copy.negative-parallelism", recognition="copy-negative-parallelism", severity=3)
def r_neg_parallel(doc: CopyDoc):
    """'Not just X, but Y' and its relatives."""
    yield from _scan(doc, NEGATIVE_PARALLEL_RE, 0.85)


@rule("copy.fast-paced-opener", recognition="copy-fast-paced-world-opener", severity=4)
def r_opener(doc: CopyDoc):
    """'In today's fast-paced world' style throat-clearing opener."""
    yield from _scan(doc, OPENER_RE, 0.95)


@rule("copy.emoji-bullets", recognition="copy-emoji-bullets", severity=3)
def r_emoji_bullets(doc: CopyDoc):
    """List items led by emoji instead of words."""
    led = []
    for seg in doc.segments:
        body = re.sub(r"^\s*([-*+•]|\d+[.)])\s*", "", seg.raw).strip()
        if seg.kind in ("bullet", "para", "heading") and body and is_emoji(body[0]):
            led.append((seg, body[0]))
    if len(led) >= EMOJI_BULLET_MIN:
        for seg, ch in led[:20]:
            yield hit(f"line {seg.line}", f"U+{ord(ch):04X} leads: {seg.text[:60]}", 0.9)


@rule("copy.empty-superlative", recognition="copy-empty-superlatives", severity=3)
def r_superlative(doc: CopyDoc):
    """Superlative claim with no number or comparison to back it."""
    for seg in doc.segments:
        for sentence in re.split(r"(?<=[.!?])\s+", seg.text):
            m = SUPERLATIVE_RE.search(sentence)
            if m and not re.search(r"\d", sentence):
                yield hit(f"line {seg.line}", f"'{m.group(0)}' with no measurable claim: "
                          f"{sentence[:70]}", 0.85)


@rule("copy.whether-hedge", recognition="copy-whether-you-are-hedge", severity=3)
def r_whether(doc: CopyDoc):
    """'Whether you are a X or a Y' audience hedge."""
    yield from _scan(doc, WHETHER_RE, 0.9)


@rule("copy.closing-offer", recognition="copy-ready-to-get-started", severity=3)
def r_closing(doc: CopyDoc):
    """Closing offer such as 'Ready to get started?'."""
    yield from _scan(doc, CLOSING_RE, 0.85)


def _title_case(text: str):
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    if len(words) < 2:
        return None
    majors = [w for w in words[1:] if w.lower() not in MINOR_WORDS and not w.isupper()]
    if len(majors) < TITLE_MIN_MAJOR_WORDS:
        return None
    return all(w[0].isupper() for w in majors)


@rule("copy.title-case-headings", recognition="copy-title-case-headings", severity=2)
def r_title_case(doc: CopyDoc):
    """Title Case On Every Word in UI and doc headings."""
    judged = [(s, _title_case(s.text)) for s in doc.segments if s.kind == "heading"]
    judged = [(s, t) for s, t in judged if t is not None]
    titled = [s for s, t in judged if t]
    if len(titled) >= TITLE_MIN_HEADINGS and len(titled) / len(judged) >= TITLE_MIN_RATIO:
        for s in titled[:20]:
            yield hit(f"line {s.line}", f"title case heading: {s.text[:60]}", 0.8)


@rule("copy.sycophantic-opener", recognition="copy-sycophantic-opener", severity=3)
def r_sycophant(doc: CopyDoc):
    """Reply opens with 'Great question!' or 'Absolutely!'."""
    for seg in doc.segments[:3]:
        m = SYCOPHANT_RE.search(seg.text)
        if m:
            yield hit(f"line {seg.line}", f"opener '{m.group(0).strip()}'", 0.9)


@rule("copy.question-reveal", recognition="copy-question-reveal", severity=3)
def r_reveal(doc: CopyDoc):
    """Rhetorical 'The result?' reveal."""
    yield from _scan(doc, REVEAL_RE, 0.85)
