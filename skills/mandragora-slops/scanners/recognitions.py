"""Recognition library: load, validate, dedupe, append, rebuild INDEX.md.

A recognition is one ASCII file .recognitions/<domain>/<id>.slop.txt whose
format is specified in .recognitions/FORMAT.md. This module is the only code
that writes to the library.

CLI (run from the skill directory):
    python -m scanners.recognitions validate [--root DIR]
    python -m scanners.recognitions index    [--root DIR]
    python -m scanners.recognitions add DRAFT|- [--source PATH] [--reason TEXT] [--root DIR]
    python -m scanners.recognitions hit ID [ID ...] [--root DIR]
    python -m scanners.recognitions list [--domain D] [--root DIR]
    python -m scanners.recognitions template DOMAIN

Exit codes: 0 = ok, 1 = validation failures, 2 = usage or I/O error.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = SKILL_DIR / ".recognitions"

SECTIONS = (
    "ID", "DOMAIN", "NAME", "SEVERITY", "SIGNATURE", "SIGNALS", "STATIC_RULES", "WHY",
    "ASCII_SLOP", "FIX", "ASCII_FIXED", "SOURCE", "FIRST_SEEN", "HITS",
)
INLINE = frozenset({"ID", "DOMAIN", "NAME", "SEVERITY", "SIGNATURE", "STATIC_RULES",
                    "SOURCE", "FIRST_SEEN", "HITS"})
BLOCK = frozenset({"SIGNALS", "WHY", "FIX"})
FENCES = {"ASCII_SLOP": "+--SLOP--", "ASCII_FIXED": "+--FIXED--"}
FENCE_END = "+--END--"
RUNTIME_FIELDS = ("SOURCE", "FIRST_SEEN", "HITS")

MAX_COLUMNS = 100           # every line, art included, fits a 100 column terminal
MIN_SIGNALS = 2             # one bullet is a hunch, two make an observable pattern
MIN_SIGNAL_WORDS = 4        # shorter bullets tend to be labels, not observations
MAX_WHY_SENTENCES = 3       # FORMAT.md: WHY is 1 to 3 sentences
NAME_MIN, NAME_MAX = 3, 80  # short human name, fits one index table cell
RUBRIC_ONLY = "none (rubric only)"
UNSEEN = "unseen"
SOURCES = ("seed", "learned")

HEADER_RE = re.compile(r"^([A-Z_]+):(.*)$")
ID_RE = re.compile(r"^([a-z0-9]+)-[a-z0-9]+(?:-[a-z0-9]+)*$")
DOMAIN_RE = re.compile(r"^[a-z0-9]+$")
RULE_ID_RE = re.compile(r"^[a-z0-9]+\.[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# SIGNALS must describe what is observable. These phrases describe a feeling.
VAGUE_PATTERNS = (
    re.compile(r"\b(looks?|feels?|seems?)\s+(like\s+)?(an?\s+)?(ai|generic|off|cheap|fake|"
               r"soulless|bland|templated|artificial)\b", re.I),
    re.compile(r"\bgeneric[- ]looking\b", re.I),
    re.compile(r"\bai[- ](look|feel|vibe|style)s?\b", re.I),
    re.compile(r"\bvibes?\b", re.I),
)

# A FIX has to change structure or the signal carrier. Without one of these
# verbs the text is almost always a recolor or a rename of the same pattern.
STRUCTURE_WORDS = frozenset("""
    remove removes replace replaces drop drops delete merge merges split splits move moves
    swap cut collapse rebuild restructure reorder rewrite retopologize unwrap re-unwrap rebake
    re-bake bake separate weld recalculate vary break introduce convert combine join trim
    choose pick keep state print place resize reduce add stack group flatten offset lead
    name list mark limit align anchor repaint paint re-author sculpt derive pair restrict
    build
""".split())


class FormatError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


@dataclass
class Recognition:
    data: dict
    path: Path | None = None
    order: list = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.data.get("ID", "")

    @property
    def domain(self) -> str:
        return self.data.get("DOMAIN", "")

    @property
    def name(self) -> str:
        return self.data.get("NAME", "")

    @property
    def severity(self) -> int:
        try:
            return int(self.data.get("SEVERITY", "0"))
        except ValueError:
            return 0

    @property
    def signature(self) -> str:
        return normalize_signature(self.data.get("SIGNATURE", ""))

    @property
    def static_rules(self) -> list:
        return parse_static_rules(self.data.get("STATIC_RULES", ""))

    @property
    def hits(self) -> int:
        try:
            return int(self.data.get("HITS", "0"))
        except ValueError:
            return 0

    @property
    def source(self) -> str:
        return self.data.get("SOURCE", "")


# --------------------------------------------------------------------------
# Parsing and serialization
# --------------------------------------------------------------------------

def normalize_signature(sig: str) -> str:
    s = sig.strip().lower()
    s = re.sub(r"\s*\|\s*", "|", s)
    s = re.sub(r"\s*\+\s*", "+", s)
    s = re.sub(r"[\s_/]+", "-", s)
    s = re.sub(r"[^a-z0-9|+.\-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"(^|[|+])-+", r"\1", s)
    s = re.sub(r"-+($|[|+])", r"\1", s)
    return s


def parse_static_rules(value: str) -> list:
    value = value.strip()
    if not value or value == RUBRIC_ONLY:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _split_lines(text: str) -> list:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse(text: str, strict: bool = True):
    """Parse recognition text. Returns (Recognition, errors). With strict=False
    blank lines between sections are tolerated (used for learned drafts)."""
    errors = []
    lines = _split_lines(text.replace("\r\n", "\n"))
    data, order = {}, []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == "":
            if strict:
                errors.append(f"line {i + 1}: blank line outside an ASCII fence")
            i += 1
            continue
        m = HEADER_RE.match(line)
        if not m or m.group(1) not in SECTIONS:
            errors.append(f"line {i + 1}: expected a section header, got {line[:40]!r}")
            i += 1
            continue
        key, rest = m.group(1), m.group(2)
        if key in data:
            errors.append(f"line {i + 1}: duplicate section {key}")
        order.append(key)
        if key in INLINE:
            value = rest.strip()
            if not rest.startswith(" ") or not value:
                errors.append(f"line {i + 1}: {key} needs 'KEY: value' on one line")
            data[key] = value
            i += 1
        elif key in BLOCK:
            if rest.strip():
                errors.append(f"line {i + 1}: {key} content belongs on indented lines below")
            i += 1
            body = []
            while i < n:
                if lines[i].startswith("  "):
                    body.append(lines[i])
                    i += 1
                elif not strict and lines[i].strip() == "" and i + 1 < n \
                        and lines[i + 1].startswith("  "):
                    i += 1
                else:
                    break
            data[key] = body
        else:  # fenced ASCII section
            if rest.strip():
                errors.append(f"line {i + 1}: {key} art belongs inside the fence below")
            i += 1
            if i >= n or lines[i] != FENCES[key]:
                errors.append(f"line {i + 1}: {key} must be followed by the line {FENCES[key]}")
                data[key] = []
                continue
            i += 1
            body = []
            while i < n and lines[i] != FENCE_END:
                body.append(lines[i])
                i += 1
            if i >= n:
                errors.append(f"{key}: missing closing {FENCE_END}")
            else:
                i += 1
            data[key] = body
    return Recognition(data=data, order=order), errors


def serialize(data: dict) -> str:
    out = []
    for key in SECTIONS:
        value = data.get(key)
        if value is None:
            continue
        if key in INLINE:
            out.append(f"{key}: {value}")
        elif key in BLOCK:
            out.append(f"{key}:")
            out.extend(value)
        else:
            out.append(f"{key}:")
            out.append(FENCES[key])
            out.extend(value)
            out.append(FENCE_END)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _count_sentences(lines) -> int:
    text = " ".join(l.strip() for l in lines)
    return len(re.findall(r"[.!?](?=\s|$)", text))


def validate_text(text: str, path: Path | None = None, rule_ids=None, domains=None) -> list:
    """Return a list of human readable errors (empty when valid)."""
    errors = []
    for lineno, line in enumerate(text.split("\n"), 1):
        for col, ch in enumerate(line, 1):
            if not (0x20 <= ord(ch) <= 0x7E):
                errors.append(f"line {lineno} col {col}: non printable ASCII U+{ord(ch):04X}")
                break
        if len(line) > MAX_COLUMNS:
            errors.append(f"line {lineno}: {len(line)} columns, limit {MAX_COLUMNS}")
    if text and not text.endswith("\n"):
        errors.append("file must end with a newline")
    if text.endswith("\n\n"):
        errors.append("file must end with exactly one newline")

    rec, perr = parse(text, strict=True)
    errors.extend(perr)
    d = rec.data

    missing = [k for k in SECTIONS if k not in d]
    if missing:
        errors.append(f"missing sections: {', '.join(missing)}")
    present = [k for k in rec.order if k in SECTIONS]
    expected = [k for k in SECTIONS if k in present]
    if present != expected:
        errors.append(f"sections out of order: {' '.join(present)}")

    rid, dom = d.get("ID", ""), d.get("DOMAIN", "")
    m = ID_RE.match(rid)
    if not m:
        errors.append(f"ID {rid!r} must look like <domain>-<kebab-slug>")
    elif m.group(1) != dom:
        errors.append(f"ID {rid!r} must start with its DOMAIN {dom!r}")
    if not DOMAIN_RE.match(dom):
        errors.append(f"DOMAIN {dom!r} is not a lowercase identifier")
    elif domains is not None and dom not in domains:
        errors.append(f"DOMAIN {dom!r} has no registered scanner module")
    if path is not None:
        if path.name != f"{rid}.slop.txt":
            errors.append(f"file name {path.name} must be {rid}.slop.txt")
        if path.parent.name != dom:
            errors.append(f"file lives in {path.parent.name}/ but DOMAIN is {dom}")

    name = d.get("NAME", "")
    if not NAME_MIN <= len(name) <= NAME_MAX:
        errors.append(f"NAME must be {NAME_MIN}..{NAME_MAX} characters")

    sev = d.get("SEVERITY", "")
    if not (sev.isdigit() and 1 <= int(sev) <= 5):
        errors.append(f"SEVERITY {sev!r} must be an integer 1..5")

    sig = d.get("SIGNATURE", "")
    if sig != normalize_signature(sig):
        errors.append(f"SIGNATURE is not normalized; expected {normalize_signature(sig)!r}")
    if not sig.startswith(dom + "|") or sig.count("|") < 2:
        errors.append("SIGNATURE must look like <domain>|<element>|<feature+feature>")

    signals = d.get("SIGNALS", [])
    bullets = []
    for line in signals:
        if line.startswith("  - "):
            bullets.append(line[4:])
        elif line.startswith("    ") and bullets:
            bullets[-1] += " " + line.strip()
        else:
            errors.append(f"SIGNALS line {line.strip()[:30]!r} must be '  - ' bullet or 4-space"
                          " continuation")
    if len(bullets) < MIN_SIGNALS:
        errors.append(f"SIGNALS needs at least {MIN_SIGNALS} bullets")
    for b in bullets:
        if len(b.split()) < MIN_SIGNAL_WORDS:
            errors.append(f"SIGNALS bullet too short to be observable: {b!r}")
        for pat in VAGUE_PATTERNS:
            if pat.search(b):
                errors.append(f"SIGNALS bullet is vague (describe what is observable): {b!r}")
                break

    rules_value = d.get("STATIC_RULES", "")
    if rules_value != RUBRIC_ONLY:
        listed = parse_static_rules(rules_value)
        if not listed:
            errors.append(f"STATIC_RULES must list rule ids or say {RUBRIC_ONLY!r}")
        for r in listed:
            if not RULE_ID_RE.match(r):
                errors.append(f"STATIC_RULES id {r!r} must look like <domain>.<slug>")
            elif not r.startswith(dom + "."):
                errors.append(f"STATIC_RULES id {r!r} belongs to another domain")
            elif rule_ids is not None and r not in rule_ids:
                errors.append(f"STATIC_RULES id {r!r} is not a registered rule")

    for key in ("WHY", "FIX"):
        body = d.get(key, [])
        if not any(l.strip() for l in body):
            errors.append(f"{key} is empty")
    why_n = _count_sentences(d.get("WHY", []))
    if not 1 <= why_n <= MAX_WHY_SENTENCES:
        errors.append(f"WHY must be 1..{MAX_WHY_SENTENCES} sentences, found {why_n}")
    fix_words = set(re.findall(r"[a-z][a-z\-]*", " ".join(d.get("FIX", [])).lower()))
    if d.get("FIX") and not fix_words & STRUCTURE_WORDS:
        errors.append("FIX reads as a recolor: name the structural or carrier change")

    slop, fixed = d.get("ASCII_SLOP", []), d.get("ASCII_FIXED", [])
    for key, body in (("ASCII_SLOP", slop), ("ASCII_FIXED", fixed)):
        if not any(l.strip() for l in body):
            errors.append(f"{key} block is empty")
    if slop and slop == fixed:
        errors.append("ASCII_FIXED must differ from ASCII_SLOP")

    src = d.get("SOURCE", "")
    if src not in SOURCES:
        errors.append(f"SOURCE must be one of {SOURCES}")
    first = d.get("FIRST_SEEN", "")
    if first != UNSEEN:
        if not DATE_RE.match(first):
            errors.append(f"FIRST_SEEN must be {UNSEEN!r} or YYYY-MM-DD")
        else:
            try:
                datetime.date.fromisoformat(first)
            except ValueError:
                errors.append(f"FIRST_SEEN {first!r} is not a real date")
    if src == "learned" and first == UNSEEN:
        errors.append("learned recognitions carry the date they were added in FIRST_SEEN")
    hits = d.get("HITS", "")
    if not hits.isdigit():
        errors.append("HITS must be a non-negative integer")
    elif (int(hits) == 0) != (first == UNSEEN) and src == "seed":
        errors.append("seed recognitions have HITS 0 exactly while FIRST_SEEN is unseen")
    return errors


# --------------------------------------------------------------------------
# Library operations
# --------------------------------------------------------------------------

def _registry():
    """Rule ids and domain names from the scanner registry."""
    from scanners import core

    core.load_scanners()
    return set(core.RULES), set(core.DOMAINS)


def library_files(root: Path) -> list:
    root = Path(root)
    return sorted(p for p in root.glob("*/*.slop.txt") if p.is_file())


def load_library(root: Path = DEFAULT_ROOT) -> list:
    recs = []
    for p in library_files(root):
        rec, _ = parse(p.read_text(encoding="ascii", errors="replace"), strict=False)
        rec.path = p
        recs.append(rec)
    return recs


def validate_library(root: Path = DEFAULT_ROOT, rule_ids=None, domains=None) -> list:
    errors = []
    seen_ids, seen_sigs = {}, {}
    for p in library_files(root):
        raw = p.read_bytes()
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            errors.append(f"{p.name}: not ASCII ({exc.reason} at byte {exc.start})")
            text = raw.decode("ascii", errors="replace")
        if "\r" in text:
            errors.append(f"{p.name}: CR characters found; FORMAT.md requires LF only")
        for e in validate_text(text, path=p, rule_ids=rule_ids, domains=domains):
            errors.append(f"{p.parent.name}/{p.name}: {e}")
        rec, _ = parse(text, strict=False)
        if rec.id in seen_ids:
            errors.append(f"{p.name}: duplicate ID also in {seen_ids[rec.id]}")
        seen_ids[rec.id] = p.name
        if rec.signature in seen_sigs:
            errors.append(f"{p.name}: duplicate SIGNATURE also in {seen_sigs[rec.signature]}")
        seen_sigs[rec.signature] = p.name
    return errors


def _today() -> str:
    return datetime.date.today().isoformat()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write(text)


def record_hits(root: Path, ids, today: str | None = None) -> list:
    """Increment HITS (and fill FIRST_SEEN when unseen) for each id.
    Returns ids that were not found. Rewrites only those two lines."""
    root = Path(root)
    today = today or _today()
    by_id = {p.name[: -len(".slop.txt")]: p for p in library_files(root)}
    missing = []
    for rid in ids:
        p = by_id.get(rid)
        if p is None:
            missing.append(rid)
            continue
        text = p.read_text(encoding="ascii")
        text = re.sub(r"(?m)^HITS: (\d+)$", lambda m: f"HITS: {int(m.group(1)) + 1}", text, count=1)
        text = re.sub(r"(?m)^FIRST_SEEN: " + UNSEEN + "$", f"FIRST_SEEN: {today}", text, count=1)
        _write(p, text)
    rebuild_index(root)
    return missing


def _cell(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ").strip()


def append_ledger(root: Path, date: str, rid: str, source: str, reason: str) -> None:
    path = Path(root) / "LEDGER.md"
    if not path.exists():
        _write(path, LEDGER_HEADER)
    row = f"| {_cell(date)} | {_cell(rid)} | {_cell(source) or '-'} | {_cell(reason) or '-'} |\n"
    with open(path, "a", encoding="ascii", errors="replace", newline="\n") as fh:
        fh.write(row)


LEDGER_HEADER = """# Learned recognition ledger

Append-only log of recognitions added by `python -m scanners.recognitions add`.
One row per learned recognition. Duplicates do not get a row; they raise HITS instead.
The date column is written by the script at run time.

| Date | ID | Input source | Reason |
|------|----|--------------|--------|
"""


def rebuild_index(root: Path = DEFAULT_ROOT) -> str:
    root = Path(root)
    recs = sorted(load_library(root), key=lambda r: (r.domain, r.id))
    counts = {}
    for r in recs:
        counts[r.domain] = counts.get(r.domain, 0) + 1
    summary = ", ".join(f"{d} {c}" for d, c in sorted(counts.items()))
    lines = [
        "# Recognition index",
        "",
        "Generated by `python -m scanners.recognitions index`. Edits by hand are overwritten.",
        "",
        f"Total: {len(recs)} recognitions ({summary}).",
        "",
        "| ID | Domain | Name | Severity | Static rules | Hits |",
        "|----|--------|------|----------|--------------|------|",
    ]
    for r in recs:
        rules = ", ".join(r.static_rules) or RUBRIC_ONLY
        lines.append(f"| {r.id} | {r.domain} | {_cell(r.name)} | {r.severity} | {rules} | {r.hits} |")
    text = "\n".join(lines) + "\n"
    _write(root / "INDEX.md", text)
    return text


def add(root: Path, draft: str, source: str = "", reason: str = "", today: str | None = None,
        rule_ids=None, domains=None):
    """Add a learned recognition from draft text.

    Returns (status, id, hits) where status is 'created' or 'duplicate'.
    Raises FormatError when the draft does not validate."""
    root = Path(root)
    today = today or _today()
    rec, perr = parse(draft, strict=False)
    if perr:
        raise FormatError(perr)
    data = dict(rec.data)
    data["SOURCE"] = "learned"
    data["FIRST_SEEN"] = today
    data["HITS"] = "1"
    if "SIGNATURE" in data:
        data["SIGNATURE"] = normalize_signature(data["SIGNATURE"])
    text = serialize(data)
    if rule_ids is None or domains is None:
        reg_rules, reg_domains = _registry()
        rule_ids = reg_rules if rule_ids is None else rule_ids
        domains = reg_domains if domains is None else domains
    errors = validate_text(text, rule_ids=rule_ids, domains=domains)
    if errors:
        raise FormatError(errors)
    new = Recognition(data=data)
    library = load_library(root)
    for existing in library:
        if existing.signature == new.signature:
            record_hits(root, [existing.id], today=today)
            return "duplicate", existing.id, existing.hits + 1
    for existing in library:
        if existing.id == new.id:
            raise FormatError([f"ID {new.id} exists with a different SIGNATURE; choose a new ID"
                               " or reuse the existing SIGNATURE"])
    _write(root / new.domain / f"{new.id}.slop.txt", text)
    append_ledger(root, today, new.id, source, reason)
    rebuild_index(root)
    return "created", new.id, 1


TEMPLATE = """ID: {domain}-short-kebab-slug
DOMAIN: {domain}
NAME: Short human name
SEVERITY: 3
SIGNATURE: {domain}|element|feature-one+feature-two
SIGNALS:
  - First observable feature with a measurable or visible property
  - Second observable feature that co-occurs with the first one
STATIC_RULES: none (rubric only)
WHY:
  One to three sentences on why this pattern reads as machine generated.
ASCII_SLOP:
+--SLOP--
  draw the slop element here in printable ASCII
+--END--
FIX:
  Replace or remove the structure that carries the signal; name the new carrier.
ASCII_FIXED:
+--FIXED--
  draw the corrected element here
+--END--
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scanners.recognitions",
                                     description="Mandragora recognition library tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "index", "list"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", default=str(DEFAULT_ROOT))
        if name == "list":
            sp.add_argument("--domain")
    sp = sub.add_parser("add", help="add a learned recognition from a draft file ('-' = stdin)")
    sp.add_argument("draft")
    sp.add_argument("--source", default="", help="input path the slop was found in")
    sp.add_argument("--reason", default="", help="one line on why it was added")
    sp.add_argument("--root", default=str(DEFAULT_ROOT))
    sp = sub.add_parser("hit", help="increment HITS for matched recognition ids")
    sp.add_argument("ids", nargs="+")
    sp.add_argument("--root", default=str(DEFAULT_ROOT))
    sp = sub.add_parser("template", help="print a draft skeleton for a domain")
    sp.add_argument("domain")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0

    if args.cmd == "template":
        print(TEMPLATE.format(domain=args.domain), end="")
        return 0

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    if args.cmd == "validate":
        rule_ids, domains = _registry()
        errors = validate_library(root, rule_ids=rule_ids, domains=domains)
        for e in errors:
            print(e)
        n = len(library_files(root))
        print(f"{n} recognition file(s), {len(errors)} error(s)")
        return 1 if errors else 0

    if args.cmd == "index":
        rebuild_index(root)
        print(f"wrote {root / 'INDEX.md'}")
        return 0

    if args.cmd == "list":
        for r in sorted(load_library(root), key=lambda r: (r.domain, r.id)):
            if args.domain and r.domain != args.domain:
                continue
            print(f"{r.id:<48} sev {r.severity}  hits {r.hits:<4} {r.name}")
        return 0

    if args.cmd == "hit":
        missing = record_hits(root, args.ids)
        for m in missing:
            print(f"warning: no recognition named {m}", file=sys.stderr)
        return 2 if missing else 0

    if args.cmd == "add":
        try:
            draft = sys.stdin.read() if args.draft == "-" else \
                Path(args.draft).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            status, rid, hits = add(root, draft, source=args.source, reason=args.reason)
        except FormatError as exc:
            for e in exc.errors:
                print(f"invalid: {e}", file=sys.stderr)
            return 1
        print(f"{status} {rid} (HITS {hits})")
        return 0
    return 2


if __name__ == "__main__":
    from scanners import recognitions as _recs

    sys.exit(_recs.main())
