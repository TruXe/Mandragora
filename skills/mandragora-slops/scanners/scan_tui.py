"""TUI domain: terminal output, ANSI captures, CLI help and status output.

Input is captured terminal output (.ansi/.ans, or .txt/.log containing escape
sequences or box drawing). Escape sequences may be raw ESC bytes or the
printable notations that logs use: ^[ (cat -v), \\x1b, \\033, \\e, \\u001b.
Carriage returns are kept as frames so spinners and progress redraws can be
analysed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scanners.core import emoji_in, hit, is_emoji, read_bytes, register_domain, rule

DOMAIN = "tui"
EXTENSIONS = (".ansi", ".ans", ".log", ".out", ".txt")

# ---------------------------------------------------------------- thresholds
# Distinct foreground colors on one line. Two or three is semantic coloring
# (error red, dim metadata); four or more is decoration.
RAINBOW_MIN_COLORS = 4
# Color switches between consecutive words on one line, with 3+ colors in play.
RAINBOW_MIN_WORD_SWITCHES = 3
# Framed lines / non-empty lines above this share means every block is boxed.
FRAME_COVERAGE_MIN = 0.8
FRAME_MIN_COUNT = 3
# Centered banner text: padding difference tolerated, minimum side padding.
BANNER_CENTER_TOLERANCE = 2
BANNER_MIN_PAD = 2
# Progress values needed to judge the step pattern of a progress bar.
PROGRESS_MIN_STEPS = 3
# Spinner redraws with an unchanged message and no counter.
SPINNER_MIN_FRAMES = 4
# Emoji-led status lines needed before markers count as a pattern.
EMOJI_STATUS_MIN = 2
# Rows in a two column boxed table, and the share of each cell left as padding.
KV_TABLE_MIN_ROWS = 3
KV_PADDING_MIN = 0.25
# ASCII art detection: share of art characters among non-space characters,
# minimum line length, and consecutive lines forming one banner block.
ART_MIN_RATIO = 0.85
ART_MIN_LEN = 10
ART_BLOCK_MIN_LINES = 3
# Banner lines over this share of all non-empty lines dominate the output.
ART_DOMINANCE = 0.5

ESC = "\x1b"
NOTATION_RE = re.compile(r"\^\[|\\x1[bB]|\\033|\\e(?=\[)|\\u001[bB]")
SGR_RE = re.compile("\x1b\\[([0-9;]*)m")
OTHER_ESC_RE = re.compile("\x1b\\[[0-9;?]*[A-Za-ln-z]|\x1b\\][^\x07]*(?:\x07|\x1b\\\\)|\x1b[()][A-Z0-9]")

TOP_LEFT = "┌╭╔╓╒┏"      # light, rounded, double, heavy corners
HORIZONTAL = "─═━"
VERTICAL = "│║┃"
BOX_CHARS = set(TOP_LEFT + HORIZONTAL + VERTICAL +
                "┐╮╗╖╕┓└╰╚╙╘┗"
                "┘╯╝╜╛┛├┤┬┴┼╠"
                "╣╦╩╬")
BAR_RE = re.compile("[█▓▒░■□▰▱━●○]{4,}"
                    r"|\[[#=>\-\s.]{6,}\]")
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
SPINNER_CHARS = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏|/-\\")
ART_CHARS = set("_|/\\()`'.,-=#<>[]{}~^*:;") | set(
    "█▀▄▌▐░▒▓╗╔╝╚║═")
SUCCESS_RE = re.compile(
    r"^[\W_]*(success(?:fully)?|done|all set|all done|awesome|great|perfect|complete|completed|"
    r"finished|hooray|woohoo|yay|congratulations|congrats|you(?:'re| are) all set|"
    r"everything is (?:ready|set up|done))\b[^0-9/\\]*!+[\W_]*$", re.I)


@dataclass
class Line:
    number: int
    plain: str                     # visible text after the last carriage return frame
    spans: list                    # (text, fg) pairs of the visible frame
    frames: list = field(default_factory=list)   # plain text of every \r frame


@dataclass
class TuiDoc:
    path: Path
    lines: list


def _apply_sgr(params: str, fg):
    codes = [int(p) if p.isdigit() else 0 for p in params.split(";")] if params else [0]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c in (0, 39):
            fg = None
        elif 30 <= c <= 37:
            fg = f"c{c - 30}"
        elif 90 <= c <= 97:
            fg = f"b{c - 90}"
        elif c == 38 and i + 2 < len(codes) and codes[i + 1] == 5:
            fg = f"x{codes[i + 2]}"
            i += 2
        elif c == 38 and i + 4 < len(codes) and codes[i + 1] == 2:
            fg = "rgb" + ",".join(str(v) for v in codes[i + 2:i + 5])
            i += 4
        elif c in (48,) and i + 1 < len(codes):
            i += 2 if codes[i + 1] == 5 else 4 if codes[i + 1] == 2 else 0
        i += 1
    return fg


def _parse_frame(raw: str, fg):
    raw = OTHER_ESC_RE.sub("", raw)
    spans, pos = [], 0
    for m in SGR_RE.finditer(raw):
        if m.start() > pos:
            spans.append((raw[pos:m.start()], fg))
        fg = _apply_sgr(m.group(1), fg)
        pos = m.end()
    if pos < len(raw):
        spans.append((raw[pos:], fg))
    plain = "".join(t for t, _ in spans).replace(ESC, "")
    return plain, spans, fg


def parse_tui(text: str, path: Path | None = None) -> TuiDoc:
    text = NOTATION_RE.sub(ESC, text)
    lines, fg = [], None
    for n, raw in enumerate(text.split("\n"), 1):
        frames = raw.split("\r")
        parsed = []
        for fr in frames:
            plain, spans, fg = _parse_frame(fr, fg)
            parsed.append((plain, spans))
        visible = next((p for p in reversed(parsed) if p[0].strip()), parsed[-1])
        lines.append(Line(n, visible[0].expandtabs(4), visible[1], [p[0] for p in parsed]))
    return TuiDoc(path or Path("inline.ansi"), lines)


def load(path: Path) -> TuiDoc:
    # Keep lone carriage returns: they separate spinner and progress redraw frames.
    text = read_bytes(path).decode("utf-8", errors="replace").replace("\r\n", "\n")
    return parse_tui(text.lstrip("﻿"), path)


def sniff(path: Path, head: bytes) -> int:
    ext = path.suffix.lower()
    if ext in (".ansi", ".ans"):
        return 90
    if ext not in (".txt", ".log", ".out"):
        return 0
    if b"\x1b[" in head or re.search(rb"\^\[\[|\\x1b\[|\\033\[", head):
        return 85
    text = head.decode("utf-8", errors="ignore")
    if not text:
        return 0
    box = sum(1 for ch in text if ch in BOX_CHARS)
    prompts = len(re.findall(r"(?m)^\$ \S", text))
    if box / max(1, len(text)) >= 0.01 or prompts >= 1:
        return 60
    return 0


register_domain(DOMAIN, load=load, sniff=sniff, extensions=EXTENSIONS,
                description="Terminal output, ANSI captures, CLI help and status text")


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

@rule("tui.rainbow-sgr", recognition="tui-rainbow-ansi", severity=4)
def r_rainbow(doc: TuiDoc):
    """Four or more foreground colors on a line, or per-word color switching."""
    found = 0
    for line in doc.lines:
        words = []
        for text, fg in line.spans:
            for w in text.split():
                words.append((w, fg))
        colors = {fg for _, fg in words if fg is not None}
        switches = sum(1 for a, b in zip(words, words[1:]) if a[1] != b[1])
        if len(colors) >= RAINBOW_MIN_COLORS or (len(colors) >= 3 and
                                                 switches >= RAINBOW_MIN_WORD_SWITCHES):
            found += 1
            if found <= 10:
                yield hit(f"line {line.number}", f"{len(colors)} colors, {switches} switches: "
                          f"{line.plain.strip()[:60]}", 0.9)


def _is_top_border(s: str) -> bool:
    s = s.strip()
    return len(s) >= 3 and s[0] in TOP_LEFT and any(ch in HORIZONTAL for ch in s[1:4])


@rule("tui.box-frame-emoji-title", recognition="tui-emoji-title-box-frames", severity=3)
def r_box_frames(doc: TuiDoc):
    """Box-drawing frame around every block, emoji in the frame title."""
    tops = [l for l in doc.lines if _is_top_border(l.plain)]
    titled = [l for l in tops if emoji_in(l.plain)]
    for l in titled[:10]:
        yield hit(f"line {l.number}", f"emoji frame title: {l.plain.strip()[:60]}", 0.9)
    if titled:
        return
    nonempty = [l for l in doc.lines if l.plain.strip()]
    framed = [l for l in nonempty if l.plain.strip()[0] in BOX_CHARS]
    if len(tops) >= FRAME_MIN_COUNT and nonempty and \
            len(framed) / len(nonempty) >= FRAME_COVERAGE_MIN:
        yield hit(f"line {tops[0].number}", f"{len(tops)} frames cover "
                  f"{len(framed)}/{len(nonempty)} lines", 0.75)


def _centered(inner: str) -> bool:
    left = len(inner) - len(inner.lstrip())
    right = len(inner) - len(inner.rstrip())
    return inner.strip() != "" and min(left, right) >= BANNER_MIN_PAD and \
        abs(left - right) <= BANNER_CENTER_TOLERANCE


@rule("tui.double-line-banner", recognition="tui-centered-double-banner", severity=3)
def r_banner(doc: TuiDoc):
    """Centered title inside a double-line box or between full-width rules."""
    ls = doc.lines
    for i in range(len(ls) - 2):
        a, b, c = ls[i].plain.strip(), ls[i + 1].plain.strip(), ls[i + 2].plain.strip()
        if a.startswith("╔") and set(a[1:-1]) <= {"═"} and len(a) > 6 and \
                b.startswith("║") and b.endswith("║") and _centered(b[1:-1]):
            yield hit(f"line {ls[i].number}", f"double-line banner: {b[1:-1].strip()[:50]}", 0.9)
        elif re.fullmatch(r"[=#*~]{12,}", a) and re.fullmatch(r"[=#*~]{12,}", c) and \
                _centered(ls[i + 1].plain.rstrip().ljust(len(a))[:len(a)]):
            yield hit(f"line {ls[i].number}", f"ruled centered banner: {b[:50]}", 0.8)


def _progress_values(doc: TuiDoc) -> list:
    vals = []
    for line in doc.lines:
        for fr in line.frames:
            if BAR_RE.search(fr):
                m = PCT_RE.search(fr)
                if m:
                    vals.append((line.number, float(m.group(1))))
    return vals


@rule("tui.fake-progress", recognition="tui-fake-progress", severity=3)
def r_fake_progress(doc: TuiDoc):
    """Progress bars advancing in perfectly even steps, or label-only spinners."""
    vals = _progress_values(doc)
    run = []
    for item in vals + [(None, -1.0)]:
        if run and item[1] > run[-1][1]:
            run.append(item)
            continue
        if len(run) >= PROGRESS_MIN_STEPS:
            diffs = {round(b[1] - a[1], 3) for a, b in zip(run, run[1:])}
            if len(diffs) == 1:
                yield hit(f"line {run[0][0]}", f"progress jumps by exactly {diffs.pop():g}% "
                          f"over {len(run)} redraws ({run[0][1]:g}% -> {run[-1][1]:g}%)", 0.85)
        run = [item] if item[0] is not None else []
    # Spinner redraws arrive as carriage-return frames on one line, or as
    # consecutive lines when the capture tool expanded them.
    groups = [(line.number, [f.strip() for f in line.frames if f.strip()]) for line in doc.lines]
    run_start, run = None, []
    for line in doc.lines + [Line(0, "", [])]:
        s = line.plain.strip()
        if s[:1] in SPINNER_CHARS and s[1:2] == " ":
            run_start = run_start or line.number
            run.append(s)
            continue
        if len(run) >= SPINNER_MIN_FRAMES:
            groups.append((run_start, run))
        run_start, run = None, []
    reported = set()
    for number, frames in groups:
        spin = [f for f in frames if f[:1] in SPINNER_CHARS and f[1:2] == " "]
        if len(spin) >= SPINNER_MIN_FRAMES and number not in reported:
            labels = {f[1:].strip() for f in spin}
            if len(labels) == 1 and not re.search(r"\d", next(iter(labels))):
                reported.add(number)
                yield hit(f"line {number}", f"{len(spin)} spinner frames, one label, no "
                          f"counter: {spin[0][1:].strip()[:40]}", 0.8)


def _leading_emoji(text: str) -> str:
    s = re.sub(r"^[\s\-*>\[\]()]+", "", text)
    return s[0] if s and is_emoji(s[0]) else ""


@rule("tui.emoji-status", recognition="tui-emoji-status-markers", severity=3)
def r_emoji_status(doc: TuiDoc):
    """Emoji used as the status marker at the start of output lines."""
    marked = [l for l in doc.lines if _leading_emoji(l.plain)]
    if len(marked) >= EMOJI_STATUS_MIN:
        for l in marked[:10]:
            yield hit(f"line {l.number}", f"U+{ord(_leading_emoji(l.plain)):04X} status marker: "
                      f"{l.plain.strip()[1:50].strip()}", 0.85)


KV_ROW_RE = re.compile("^\\s*[│┃|]([^│┃|]+)[│┃|]"
                       "([^│┃|]+)[│┃|]\\s*$")
BORDER_RE = re.compile("^\\s*([┌├└╭╰╔╚╠+][─═"
                       "━┬┼┴╦╬╩+=-]+"
                       "[┐┤┘╮╯╗╣╝+]?)\\s*$")


@rule("tui.boxed-kv-table", recognition="tui-boxed-key-value-table", severity=3)
def r_kv_table(doc: TuiDoc):
    """Two-column key/value data drawn as a padded, fully boxed table."""
    rows, pads, first = 0, [], None
    has_border = any(BORDER_RE.match(l.plain) for l in doc.lines)
    for l in doc.lines:
        m = KV_ROW_RE.match(l.plain)
        if not m:
            continue
        rows += 1
        first = first or l.number
        for cell in m.groups():
            if cell.strip():
                pads.append(1.0 - len(cell.strip()) / len(cell))
    if has_border and rows >= KV_TABLE_MIN_ROWS and pads and \
            sum(pads) / len(pads) >= KV_PADDING_MIN:
        yield hit(f"line {first}", f"{rows} boxed key/value rows, "
                  f"{100 * sum(pads) / len(pads):.0f}% of each cell is padding", 0.8)


def _is_art(s: str) -> bool:
    t = s.strip()
    if len(t) < ART_MIN_LEN or re.fullmatch(r"[-=_+|]+", t):
        return False
    chars = [ch for ch in t if not ch.isspace()]
    return sum(1 for ch in chars if ch in ART_CHARS) / len(chars) >= ART_MIN_RATIO


@rule("tui.repeated-banner", recognition="tui-ascii-logo-every-command", severity=3)
def r_repeated_banner(doc: TuiDoc):
    """ASCII-art logo printed again on each command, or dominating the output."""
    blocks, cur = [], []
    for l in doc.lines + [Line(0, "", [])]:
        if _is_art(l.plain):
            cur.append(l)
            continue
        if len(cur) >= ART_BLOCK_MIN_LINES:
            blocks.append(cur)
        cur = []
    if not blocks:
        return
    keys = {}
    for b in blocks:
        keys.setdefault(tuple(x.plain.strip() for x in b), []).append(b[0].number)
    for key, starts in keys.items():
        if len(starts) >= 2:
            yield hit(f"line {starts[0]}", f"{len(key)}-line ASCII logo printed {len(starts)} "
                      f"times (lines {', '.join(map(str, starts))})", 0.9)
            return
    art = sum(len(b) for b in blocks)
    nonempty = sum(1 for l in doc.lines if l.plain.strip())
    if nonempty and art / nonempty >= ART_DOMINANCE:
        yield hit(f"line {blocks[0][0].number}", f"ASCII logo is {art} of {nonempty} output "
                  "lines", 0.75)


@rule("tui.empty-success", recognition="tui-exclamation-success", severity=3)
def r_empty_success(doc: TuiDoc):
    """Exclamation success line that carries no count, path or identifier."""
    n = 0
    for l in doc.lines:
        text = "".join(ch for ch in l.plain if not is_emoji(ch) and ch != "️").strip()
        if text and SUCCESS_RE.match(text):
            n += 1
            if n <= 10:
                yield hit(f"line {l.number}", f"no data in success line: {text[:50]}", 0.85)
