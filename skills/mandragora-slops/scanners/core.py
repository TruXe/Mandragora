"""Scanner core: Finding model, rule registry, domain auto-detection and CLI.

This module is domain-agnostic. Each scan_<domain>.py module registers itself
with register_domain() and decorates its checks with @rule(...). Nothing in
this file names a concrete domain, so a new domain only needs a new module.

CLI (run from the skill directory):
    python -m scanners.core scan <path> [<path> ...] [--domain D[,D2]] [--json]
                                 [--min-severity N] [--record]
    python -m scanners.core detect <path> [<path> ...]
    python -m scanners.core rules [--domain D]

Exit codes: 0 = no findings at or above --min-severity, 1 = findings, 2 = error.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

SKILL_DIR = Path(__file__).resolve().parent.parent
RECOGNITIONS_DIR = SKILL_DIR / ".recognitions"

# Bytes read for content sniffing. 64 KiB covers imports and framework markers
# that sit near the top of source files without reading large assets twice.
SNIFF_BYTES = 64 * 1024

# Inputs above this size are refused: the pure-Python decoders would take
# minutes, and a slop review never needs a file this large.
MAX_INPUT_BYTES = 96 * 1024 * 1024

# Evidence strings are cut to this length so reports stay readable.
EVIDENCE_MAX_CHARS = 160

# Directories never descended into when a folder is scanned.
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".recognitions",
    ".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache",
})

RULE_ID_RE = re.compile(r"^[a-z0-9]+\.[a-z0-9]+(?:-[a-z0-9]+)*$")
RECOGNITION_ID_RE = re.compile(r"^[a-z0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$")
DOMAIN_NAME_RE = re.compile(r"^[a-z0-9]+$")


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """One recognized slop element in one input."""

    rule_id: str
    recognition_id: str
    domain: str
    severity: int
    location: str
    evidence: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Hit:
    """What a rule function returns; core turns hits into Findings."""

    location: str
    evidence: str
    confidence: float = 0.8


@dataclass(frozen=True)
class Rule:
    rule_id: str
    domain: str
    recognition_id: str
    severity: int
    func: Callable
    description: str = ""


@dataclass(frozen=True)
class Domain:
    name: str
    load: Callable[[Path], object]
    sniff: Callable[[Path, bytes], int]
    extensions: tuple = ()
    description: str = ""


@dataclass
class ScanResult:
    path: str
    domains: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class ScanError(Exception):
    """Raised by loaders for unreadable or unsupported inputs."""


RULES: dict[str, Rule] = {}
DOMAINS: dict[str, Domain] = {}
_SCANNERS_LOADED = False


# --------------------------------------------------------------------------
# Registration API used by scan_<domain>.py modules
# --------------------------------------------------------------------------

def register_domain(name: str, *, load, sniff, extensions=(), description: str = "") -> None:
    if not DOMAIN_NAME_RE.match(name):
        raise ValueError(f"invalid domain name {name!r}")
    DOMAINS[name] = Domain(name, load, sniff, tuple(extensions), description)


def rule(rule_id: str, *, recognition: str, severity: int, description: str = ""):
    """Decorator registering a check. The function takes the loaded document
    and returns an iterable of Hit objects (or None)."""

    if not RULE_ID_RE.match(rule_id):
        raise ValueError(f"rule id {rule_id!r} must look like <domain>.<slug>")
    if not RECOGNITION_ID_RE.match(recognition):
        raise ValueError(f"recognition id {recognition!r} is malformed")
    if not 1 <= int(severity) <= 5:
        raise ValueError(f"severity for {rule_id} must be 1..5")
    domain = rule_id.split(".", 1)[0]
    if not recognition.startswith(domain + "-"):
        raise ValueError(f"{rule_id} maps to {recognition}, which belongs to another domain")

    def wrap(func):
        if rule_id in RULES:
            raise ValueError(f"duplicate rule id {rule_id}")
        doc = description or ((func.__doc__ or "").strip().splitlines() or [""])[0]
        RULES[rule_id] = Rule(rule_id, domain, recognition, int(severity), func, doc)
        return func

    return wrap


def hit(location, evidence, confidence: float = 0.8) -> Hit:
    return Hit(str(location), clip(str(evidence)), round(float(confidence), 2))


# --------------------------------------------------------------------------
# Small generic helpers shared by several domain modules
# --------------------------------------------------------------------------

def clip(text: str, limit: int = EVIDENCE_MAX_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def line_of(text: str, offset: int) -> int:
    """1-based line number of a character offset."""
    return text.count("\n", 0, offset) + 1


def read_text(path: Path) -> str:
    data = read_bytes(path)
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def read_bytes(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise ScanError(f"{path} is {size} bytes, above the {MAX_INPUT_BYTES} byte limit")
    return path.read_bytes()


def is_emoji(ch: str) -> bool:
    """True for pictographic code points used as emoji (generic Unicode test)."""
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF      # pictographs, emoticons, transport, symbols
        or 0x2600 <= cp <= 0x27BF     # misc symbols and dingbats (check, cross, sparkles)
        or 0x1F000 <= cp <= 0x1F2FF   # mahjong, cards, enclosed alphanumerics
        or cp in (0x2B50, 0x2B55, 0x2B06, 0x2B07, 0x2B05, 0x2B1B, 0x2B1C, 0x231A,
                  0x231B, 0x23F3, 0x23E9, 0x23EA, 0x23F0, 0x2049, 0x203C, 0x2139)
    )


def emoji_in(text: str) -> list:
    return [ch for ch in text if is_emoji(ch)]


def ascii_escape(text: str) -> str:
    """Render any string as printable ASCII (non-ASCII becomes \\uXXXX)."""
    out = []
    for ch in text:
        if 0x20 <= ord(ch) <= 0x7E:
            out.append(ch)
        elif ch == "\t":
            out.append(" ")
        else:
            cp = ord(ch)
            out.append(f"\\u{cp:04x}" if cp <= 0xFFFF else f"\\U{cp:08x}")
    return "".join(out)


def char_name(ch: str) -> str:
    return unicodedata.name(ch, f"U+{ord(ch):04X}")


# --------------------------------------------------------------------------
# Scanner discovery, detection and scanning
# --------------------------------------------------------------------------

def load_scanners() -> None:
    """Import every scanners/scan_*.py module so it can register itself."""
    global _SCANNERS_LOADED
    if _SCANNERS_LOADED:
        return
    package = importlib.import_module("scanners")
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        if info.name.startswith("scan_"):
            importlib.import_module(f"scanners.{info.name}")
    _SCANNERS_LOADED = True


def rules_for(domain: str) -> list:
    return [r for r in sorted(RULES.values(), key=lambda r: r.rule_id) if r.domain == domain]


def sniff_scores(path: Path) -> dict:
    load_scanners()
    try:
        with open(path, "rb") as fh:
            head = fh.read(SNIFF_BYTES)
    except OSError:
        head = b""
    scores = {}
    for name, dom in DOMAINS.items():
        try:
            scores[name] = int(dom.sniff(path, head))
        except Exception:  # a broken sniffer must not block other domains
            scores[name] = 0
    return scores


def detect_domain(path: Path):
    """Return (domain or None, scores). None when nothing claims the file or
    when the two best scores tie (ambiguous: the caller asks for --domain)."""
    scores = sniff_scores(path)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] <= 0:
        return None, scores
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return None, scores
    return ranked[0][0], scores


def scan_file(path, domains=None) -> ScanResult:
    load_scanners()
    path = Path(path)
    result = ScanResult(path=str(path))
    if domains:
        chosen = list(domains)
    else:
        found, scores = detect_domain(path)
        if found is None:
            claimed = {k: v for k, v in scores.items() if v > 0}
            if claimed:
                result.errors.append(f"ambiguous domain {claimed}; pass --domain")
            else:
                result.errors.append("no domain claims this file; pass --domain")
            return result
        chosen = [found]
    for name in chosen:
        if name not in DOMAINS:
            result.errors.append(f"unknown domain {name!r}; known: {', '.join(sorted(DOMAINS))}")
            continue
        result.domains.append(name)
        try:
            doc = DOMAINS[name].load(path)
        except ScanError as exc:
            result.errors.append(str(exc))
            continue
        except Exception as exc:  # loader bug or corrupt input
            result.errors.append(f"{name} loader failed: {type(exc).__name__}: {exc}")
            continue
        for r in rules_for(name):
            try:
                hits = r.func(doc) or []
            except Exception as exc:
                result.errors.append(f"rule {r.rule_id} failed: {type(exc).__name__}: {exc}")
                continue
            for h in hits:
                result.findings.append(Finding(
                    rule_id=r.rule_id, recognition_id=r.recognition_id, domain=name,
                    severity=r.severity, location=h.location, evidence=h.evidence,
                    confidence=h.confidence))
    result.findings.sort(key=lambda f: (-f.severity, f.rule_id, f.location))
    return result


def iter_inputs(paths: Iterable, forced=None):
    """Yield files to scan. Folders are walked; with a forced domain only files
    that domain's sniffer accepts are taken from folders."""
    load_scanners()
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            yield p
            continue
        if not p.is_dir():
            yield p  # scan_file reports the missing path
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                fp = Path(root) / name
                scores = sniff_scores(fp)
                if forced:
                    if any(scores.get(d, 0) > 0 for d in forced):
                        yield fp
                elif max(scores.values(), default=0) > 0:
                    yield fp


def scan_paths(paths, domains=None) -> list:
    results = []
    for p in iter_inputs(paths, domains):
        if not p.exists():
            r = ScanResult(path=str(p))
            r.errors.append("path does not exist")
            results.append(r)
            continue
        results.append(scan_file(p, domains))
    return results


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _format_text(results, min_sev: int) -> str:
    lines = []
    for res in results:
        shown = [f for f in res.findings if f.severity >= min_sev]
        tag = ",".join(res.domains) or "?"
        status = f"{len(shown)} finding(s)" if shown else "clean"
        if res.errors:
            status = "error"
        lines.append(f"{ascii_escape(res.path)}  [{tag}]  {status}")
        for err in res.errors:
            lines.append(f"  error: {ascii_escape(err)}")
        for f in shown:
            lines.append(f"  sev {f.severity}  {f.recognition_id}  ({f.rule_id})  {f.location}"
                         f"  conf {f.confidence:.2f}")
            lines.append(f"      {ascii_escape(f.evidence)}")
    total = sum(1 for r in results for f in r.findings if f.severity >= min_sev)
    ids = sorted({f.recognition_id for r in results for f in r.findings if f.severity >= min_sev})
    lines.append(f"summary: {len(results)} file(s), {total} finding(s), "
                 f"{len(ids)} recognition(s) matched")
    return "\n".join(lines)


def _to_json(results, min_sev: int) -> str:
    files = []
    matched = set()
    for res in results:
        shown = [f for f in res.findings if f.severity >= min_sev]
        matched.update(f.recognition_id for f in shown)
        files.append({
            "path": res.path,
            "domains": res.domains,
            "errors": res.errors,
            "findings": [f.to_dict() for f in shown],
        })
    total = sum(len(f["findings"]) for f in files)
    payload = {
        "min_severity": min_sev,
        "files": files,
        "findings": [f for entry in files for f in entry["findings"]],
        "recognition_ids": sorted(matched),
        "summary": {
            "files": len(files),
            "findings": total,
            "max_severity": max((f["severity"] for e in files for f in e["findings"]), default=0),
            "errors": sum(len(e["errors"]) for e in files),
        },
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def _parse_domains(value):
    if not value:
        return None
    return [d.strip() for d in value.split(",") if d.strip()]


def main(argv=None) -> int:
    load_scanners()
    parser = argparse.ArgumentParser(prog="python -m scanners.core",
                                     description="Mandragora slop scanner (Layer A)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="scan files or folders for slop")
    p_scan.add_argument("paths", nargs="+")
    p_scan.add_argument("--domain", help="force domain(s), comma separated")
    p_scan.add_argument("--json", action="store_true", help="emit JSON")
    p_scan.add_argument("--min-severity", type=int, default=1, choices=range(1, 6))
    p_scan.add_argument("--record", action="store_true",
                        help="increment HITS of matched recognitions in .recognitions/")

    p_det = sub.add_parser("detect", help="print the detected domain of each path")
    p_det.add_argument("paths", nargs="+")

    p_rules = sub.add_parser("rules", help="list registered rules")
    p_rules.add_argument("--domain")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0

    if args.cmd == "rules":
        for r in sorted(RULES.values(), key=lambda r: r.rule_id):
            if args.domain and r.domain != args.domain:
                continue
            print(f"{r.rule_id:<40} sev {r.severity}  -> {r.recognition_id}")
        return 0

    if args.cmd == "detect":
        code = 0
        for raw in args.paths:
            dom, scores = detect_domain(Path(raw))
            if dom is None:
                code = 2
            print(f"{ascii_escape(raw)}: {dom or 'unknown'}  {scores}")
        return code

    domains = _parse_domains(args.domain)
    if domains:
        unknown = [d for d in domains if d not in DOMAINS]
        if unknown:
            print(f"error: unknown domain(s) {unknown}; known: {sorted(DOMAINS)}", file=sys.stderr)
            return 2
    results = scan_paths(args.paths, domains)
    if not results:
        print("error: no scannable files found", file=sys.stderr)
        return 2
    print(_to_json(results, args.min_severity) if args.json else _format_text(results, args.min_severity))

    if args.record:
        from scanners import recognitions as recs
        ids = sorted({f.recognition_id for r in results for f in r.findings
                      if f.severity >= args.min_severity})
        if ids:
            recs.record_hits(RECOGNITIONS_DIR, ids)
            print(f"recorded hits: {', '.join(ids)}", file=sys.stderr)

    if any(r.errors for r in results):
        return 2
    if any(f.severity >= args.min_severity for r in results for f in r.findings):
        return 1
    return 0


if __name__ == "__main__":
    # Use the package module so the registry is shared with scan_* modules
    # (running as __main__ would otherwise create a second, empty registry).
    from scanners import core as _core

    sys.exit(_core.main())
