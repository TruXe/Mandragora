"""Recognition library tests: format, registry mapping, learning (add/dedupe),
plus repository hygiene checks (stdlib only, no hardcoded dates, prose audit)."""

from __future__ import annotations

import ast
import datetime
import fnmatch
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
REPO_ROOT = SKILL_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from scanners import core  # noqa: E402
from scanners import recognitions as R  # noqa: E402

core.load_scanners()
LIB = SKILL_DIR / ".recognitions"
SEED_MINIMUMS = {"web": 12, "app": 8, "tui": 8, "texture": 8, "model3d": 8, "copy": 10}
DATE_LITERAL = re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".gltf", ".obj", ".html", ".css", ".tsx", ".jsx",
                 ".vue", ".svelte", ".swift", ".kt", ".xaml", ".dart", ".qml", ".cpp", ".ansi",
                 ".gitignore", ".gitattributes", ""}

NEW_DRAFT = """ID: web-test-marquee-ticker
DOMAIN: web
NAME: Endless logo marquee ticker
SEVERITY: 2
SIGNATURE: web|social-proof|infinite-marquee+logo-ticker+css-animation
SIGNALS:
  - A row of logos animated with an infinite translateX keyframe loop
  - The row is duplicated in markup so the loop never shows a gap
STATIC_RULES: none (rubric only)
WHY:
  The ticker moves names past the reader too fast to read them.
ASCII_SLOP:
+--SLOP--
  << [A] [B] [C] [D] [A] [B] <<
+--END--
FIX:
  Replace the moving row with a static list of two named customers and their results.
ASCII_FIXED:
+--FIXED--
  Northwind: close in 4 days
+--END--
"""


def copy_library(tmp: str) -> Path:
    dest = Path(tmp) / ".recognitions"
    shutil.copytree(LIB, dest)
    return dest


class FormatTests(unittest.TestCase):
    def test_library_validates(self):
        errors = R.validate_library(LIB, rule_ids=set(core.RULES), domains=set(core.DOMAINS))
        self.assertEqual(errors, [])

    def test_seed_minimums(self):
        counts = {}
        for rec in R.load_library(LIB):
            counts[rec.domain] = counts.get(rec.domain, 0) + 1
        for domain, minimum in SEED_MINIMUMS.items():
            with self.subTest(domain=domain):
                self.assertGreaterEqual(counts.get(domain, 0), minimum)

    def test_files_are_pure_ascii_lf_and_narrow(self):
        for path in R.library_files(LIB):
            with self.subTest(file=path.name):
                raw = path.read_bytes()
                self.assertTrue(all(b == 0x0A or 0x20 <= b <= 0x7E for b in raw))
                self.assertTrue(all(len(l) <= R.MAX_COLUMNS for l in raw.split(b"\n")))

    def test_sections_in_order_and_art_present(self):
        for rec in R.load_library(LIB):
            with self.subTest(id=rec.id):
                self.assertEqual(rec.order, list(R.SECTIONS))
                self.assertTrue(any(l.strip() for l in rec.data["ASCII_SLOP"]))
                self.assertTrue(any(l.strip() for l in rec.data["ASCII_FIXED"]))

    def test_unique_ids_and_signatures(self):
        recs = R.load_library(LIB)
        self.assertEqual(len({r.id for r in recs}), len(recs))
        self.assertEqual(len({r.signature for r in recs}), len(recs))

    def test_seeds_start_unseen(self):
        for rec in R.load_library(LIB):
            if rec.source == "seed":
                with self.subTest(id=rec.id):
                    self.assertEqual(rec.data["FIRST_SEEN"], R.UNSEEN)
                    self.assertEqual(rec.hits, 0)

    def test_index_is_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = copy_library(tmp)
            self.assertEqual(R.rebuild_index(lib), (LIB / "INDEX.md").read_text(encoding="ascii"))

    def test_validator_rejects_vague_and_recolor(self):
        vague = NEW_DRAFT.replace("A row of logos animated with an infinite translateX keyframe loop",
                                  "The strip looks generic and feels AI made overall")
        errs = R.validate_text(R.serialize(dict(R.parse(vague, False)[0].data, SOURCE="seed",
                                                FIRST_SEEN="unseen", HITS="0")))
        self.assertTrue(any("vague" in e for e in errs))
        recolor = NEW_DRAFT.replace(
            "Replace the moving row with a static list of two named customers and their results.",
            "Change the purple tint to teal.")
        errs = R.validate_text(R.serialize(dict(R.parse(recolor, False)[0].data, SOURCE="seed",
                                                FIRST_SEEN="unseen", HITS="0")))
        self.assertTrue(any("recolor" in e for e in errs))


class RegistryMappingTests(unittest.TestCase):
    def test_static_rules_resolve_both_ways(self):
        recs = {r.id: r for r in R.load_library(LIB)}
        listed = set()
        for rec in recs.values():
            for rid in rec.static_rules:
                listed.add(rid)
                with self.subTest(recognition=rec.id, rule=rid):
                    self.assertIn(rid, core.RULES)
                    self.assertEqual(core.RULES[rid].recognition_id, rec.id)
                    self.assertEqual(core.RULES[rid].severity, rec.severity)
        for rid, rule in core.RULES.items():
            with self.subTest(rule=rid):
                self.assertIn(rid, listed, f"{rid} is not listed by any recognition")
                self.assertIn(rule.recognition_id, recs)

    def test_every_domain_has_library_and_rubric(self):
        for domain in core.DOMAINS:
            with self.subTest(domain=domain):
                self.assertTrue((LIB / domain).is_dir())
                self.assertTrue((SKILL_DIR / "references" / f"{domain}.md").is_file())


class LearningTests(unittest.TestCase):
    def test_add_new_pattern_creates_file_ledger_and_index(self):
        today = datetime.date.today().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            lib = copy_library(tmp)
            before = (lib / "LEDGER.md").read_text(encoding="ascii")
            status, rid, hits = R.add(lib, NEW_DRAFT, source="site/index.html",
                                      reason="ticker on landing page")
            self.assertEqual((status, rid, hits), ("created", "web-test-marquee-ticker", 1))
            path = lib / "web" / "web-test-marquee-ticker.slop.txt"
            text = path.read_text(encoding="ascii")
            self.assertIn("SOURCE: learned", text)
            self.assertIn(f"FIRST_SEEN: {today}", text)
            self.assertIn("HITS: 1", text)
            self.assertEqual(R.validate_text(text, path=path, rule_ids=set(core.RULES),
                                             domains=set(core.DOMAINS)), [])
            ledger = (lib / "LEDGER.md").read_text(encoding="ascii")
            self.assertTrue(ledger.startswith(before))
            self.assertIn(f"| {today} | web-test-marquee-ticker | site/index.html |", ledger)
            self.assertIn("| web-test-marquee-ticker | web |", (lib / "INDEX.md").read_text())

    def test_add_duplicate_signature_increments_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = copy_library(tmp)
            src = (lib / "web" / "web-pill-dot-outline-badge.slop.txt").read_text(encoding="ascii")
            draft = src.replace("ID: web-pill-dot-outline-badge", "ID: web-another-badge-name")
            files_before = len(R.library_files(lib))
            ledger_before = (lib / "LEDGER.md").read_text(encoding="ascii")
            status, rid, hits = R.add(lib, draft, source="x.html", reason="dup")
            self.assertEqual((status, rid, hits), ("duplicate", "web-pill-dot-outline-badge", 1))
            self.assertEqual(len(R.library_files(lib)), files_before)
            self.assertEqual((lib / "LEDGER.md").read_text(encoding="ascii"), ledger_before)
            text = (lib / "web" / "web-pill-dot-outline-badge.slop.txt").read_text()
            self.assertIn("HITS: 1", text)
            self.assertNotIn("FIRST_SEEN: unseen", text)
            self.assertIn("| web-pill-dot-outline-badge | web |", (lib / "INDEX.md").read_text())
            self.assertRegex((lib / "INDEX.md").read_text(),
                             r"\| web-pill-dot-outline-badge \|.*\| 1 \|")
            R.add(lib, draft, source="y.html", reason="dup again")
            self.assertIn("HITS: 2", (lib / "web" / "web-pill-dot-outline-badge.slop.txt")
                          .read_text())

    def test_add_rejects_unknown_rule_and_id_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = copy_library(tmp)
            bad_rule = NEW_DRAFT.replace("STATIC_RULES: none (rubric only)",
                                         "STATIC_RULES: web.does-not-exist")
            with self.assertRaises(R.FormatError):
                R.add(lib, bad_rule)
            collide = NEW_DRAFT.replace("ID: web-test-marquee-ticker",
                                        "ID: web-pill-dot-outline-badge")
            with self.assertRaises(R.FormatError):
                R.add(lib, collide)

    def test_cli_add_and_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = copy_library(tmp)
            draft = Path(tmp) / "draft.txt"
            draft.write_text(NEW_DRAFT, encoding="ascii")
            run = lambda *a: subprocess.run([sys.executable, "-m", "scanners.recognitions", *a],
                                            cwd=SKILL_DIR, capture_output=True, text=True,
                                            timeout=120)
            proc = run("add", str(draft), "--source", "page.html", "--reason", "seen",
                       "--root", str(lib))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("created web-test-marquee-ticker", proc.stdout)
            proc = run("add", str(draft), "--root", str(lib))
            self.assertIn("duplicate web-test-marquee-ticker (HITS 2)", proc.stdout)
            self.assertEqual(run("validate", "--root", str(lib)).returncode, 0)

    def test_scan_record_flag_raises_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = copy_library(tmp)
            missing = R.record_hits(lib, ["web-glassmorphism-card", "web-nope"])
            self.assertEqual(missing, ["web-nope"])
            rec = next(r for r in R.load_library(lib) if r.id == "web-glassmorphism-card")
            self.assertEqual(rec.hits, 1)
            self.assertTrue(R.DATE_RE.match(rec.data["FIRST_SEEN"]))


class HygieneTests(unittest.TestCase):
    def repo_files(self):
        for path in REPO_ROOT.rglob("*"):
            if ".git" in path.parts or "__pycache__" in path.parts or not path.is_file():
                continue
            yield path

    def test_standard_library_only(self):
        allowed = set(sys.stdlib_module_names) | {"scanners", "make_fixtures", "__future__"}
        for folder in (SKILL_DIR / "scanners", SKILL_DIR / "tests"):
            for path in folder.glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        names = [node.module]
                    for name in names:
                        with self.subTest(file=path.name, module=name):
                            self.assertIn(name.split(".")[0], allowed)

    def test_no_dependency_manifests(self):
        for name in ("requirements.txt", "pyproject.toml", "package.json", "Pipfile", "setup.py"):
            self.assertFalse(list(REPO_ROOT.rglob(name)), name)

    def test_no_hardcoded_dates(self):
        for path in self.repo_files():
            if path.suffix.lower() not in TEXT_SUFFIXES or path.name == "LEDGER.md":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace")
                                     .splitlines(), 1):
                if line.startswith("FIRST_SEEN:"):
                    continue   # written by the scripts at run time
                with self.subTest(file=str(path.relative_to(REPO_ROOT)), line=n):
                    self.assertIsNone(DATE_LITERAL.search(line))

    def test_gitignore_keeps_recognitions(self):
        gitignore = REPO_ROOT / ".gitignore"
        self.assertTrue(gitignore.is_file())
        targets = (".recognitions", "skills/mandragora-slops/.recognitions",
                   ".recognitions/web/web-pill-dot-outline-badge.slop.txt")
        for raw in gitignore.read_text(encoding="utf-8").splitlines():
            pat = raw.strip()
            if not pat or pat.startswith(("#", "!")):
                continue
            for target in targets:
                with self.subTest(pattern=pat, target=target):
                    self.assertFalse(fnmatch.fnmatch(target, pat.rstrip("/")))
                    self.assertFalse(fnmatch.fnmatch(target.split("/")[-1], pat.rstrip("/")))

    def test_own_prose_passes_copy_scanner(self):
        docs = [SKILL_DIR / "SKILL.md", REPO_ROOT / "README.md", REPO_ROOT / "AGENTS.md"]
        docs += sorted((SKILL_DIR / "references").glob("*.md"))
        for path in docs:
            with self.subTest(doc=path.name):
                self.assertTrue(path.is_file())
                res = core.scan_file(path, ["copy"])
                severe = [f"{f.location} {f.rule_id}: {f.evidence}" for f in res.findings
                          if f.severity >= 3]
                self.assertEqual(severe, [])
                text = path.read_text(encoding="utf-8")
                self.assertFalse([ch for ch in text if core.is_emoji(ch)], "emoji in prose")
                self.assertNotIn("—", text)


if __name__ == "__main__":
    unittest.main()
