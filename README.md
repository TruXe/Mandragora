# Mandragora

Mandragora is a repository of reusable AI agent skills. Each skill is a folder with a `SKILL.md`
that Claude Code loads directly and that other agents read through `AGENTS.md`.

## Skills

| Skill | Purpose |
|-------|---------|
| [mandragora-slops](skills/mandragora-slops/SKILL.md) | Detect AI slop in web, app, TUI, texture, 3D and copy work, record it, and redesign it without the slop signals |

## mandragora-slops

The skill reviews six domains:

| Domain | Inputs |
|--------|--------|
| web | HTML, JSX, TSX, Vue, Svelte, Astro, Blade, CSS, Tailwind classes |
| app | XAML, SwiftUI, Jetpack Compose, Flutter, QML, Dear ImGui, React Native, HTML app shells |
| tui | captured terminal output with ANSI codes, CLI help and status output |
| texture | PNG textures and material maps (albedo, roughness, normal) |
| model3d | OBJ, glTF with embedded or sidecar buffers, GLB |
| copy | Markdown, plain text, HTML text, JSON string tables |

Detection runs in two layers. Layer A is a set of deterministic scanners (59 rules) written
with the Python standard library. Layer B is a written rubric per domain that the agent scores,
with the recognition library as few-shot examples. After the report the skill writes a redesign,
renders it as ASCII and re-scans it until no finding of severity 3 or higher remains.

### Install for Claude Code

Copy or link the skill folder into a skills directory.

Personal skills (all projects):

```
cp -r skills/mandragora-slops ~/.claude/skills/
```

Project skills (one repository):

```
mkdir -p .claude/skills
cp -r /path/to/Mandragora/skills/mandragora-slops .claude/skills/
```

A symbolic link keeps the recognition library shared with this repository, so what the skill
learns lands here:

```
ln -s "$(pwd)/skills/mandragora-slops" ~/.claude/skills/mandragora-slops
```

On Windows PowerShell:

```
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\mandragora-slops" -Target "$PWD\skills\mandragora-slops"
```

Then ask Claude Code for a slop check, for example "detect AI slop in landing.html" or
"odslopuj tenhle README".

### Command line

Run these from `skills/mandragora-slops/`:

```
python -m scanners.core scan path/to/page.html
python -m scanners.core scan path/to/page.html --domain web,copy --json
python -m scanners.core scan assets/ --min-severity 3
python -m scanners.core detect path/to/file
python -m scanners.core rules
python -m scanners.ascii_render path/to/redesign.html --width 80
python -m scanners.recognitions validate
python tests/run_tests.py
```

`scan` exits 0 when clean, 1 when findings exist and 2 on errors.

### Recognition format

Each recognized slop element is one file, `.recognitions/<domain>/<id>.slop.txt`, in printable
ASCII with lines of 100 columns or fewer. The sections are ID, DOMAIN, NAME, SEVERITY,
SIGNATURE, SIGNALS, STATIC_RULES, WHY, ASCII_SLOP, FIX, ASCII_FIXED, SOURCE, FIRST_SEEN and HITS.
ASCII_SLOP and ASCII_FIXED hold a drawing of the element before and after the fix. Any model can
read the files without tooling. The full specification is in
[FORMAT.md](skills/mandragora-slops/.recognitions/FORMAT.md) and the current list in
[INDEX.md](skills/mandragora-slops/.recognitions/INDEX.md).

### How learning works

The library ships with 61 seed recognitions. During a review the agent:

1. raises HITS on every recognition it matched (`python -m scanners.recognitions hit <id>`);
2. writes a draft for each new slop element and adds it with
   `python -m scanners.recognitions add draft.slop.txt --source <input> --reason "<why>"`.

`add` validates the draft, compares its normalized SIGNATURE with the library, raises HITS on a
duplicate instead of creating a file, appends a row to `LEDGER.md` and rebuilds `INDEX.md`.
Dates in FIRST_SEEN and the ledger are written by the script when it runs.

### Adding a domain

Create `.recognitions/<domain>/`, `references/<domain>.md`, `scanners/scan_<domain>.py` (it
registers its domain and rules on import) and fixtures under `tests/fixtures/<domain>/`. The
core finds the new scanner without edits. The steps are listed in
[SKILL.md](skills/mandragora-slops/SKILL.md#adding-a-domain).

### Requirements

Python 3.10 or newer. Nothing to install: PNG decoding, mesh parsing, ANSI parsing and the test
runner use only the standard library.

## License

MIT, see [LICENSE](LICENSE).
