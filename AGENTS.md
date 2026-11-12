# Instructions for coding agents

This file is for agents other than Claude Code: Codex, Cursor, Copilot, Gemini CLI, Aider and
similar tools. Claude Code loads the same workflow from the skill directly.

## Slop review

When a task asks to detect AI slop, check that something does not look AI generated, or remove
generic AI patterns from a design, terminal output, texture, 3D model or text:

1. Open `skills/mandragora-slops/SKILL.md` and follow its workflow verbatim, steps S1 to S7, in
   order. Do not skip the learning step (S5) or the verification step (S7).
2. Run every command from `skills/mandragora-slops/`.
3. Treat `skills/mandragora-slops/.recognitions/` as the authoritative example corpus. Read the
   matching `.slop.txt` files before judging, and cite recognition ids in every report.
4. Add new recognitions only through `python -m scanners.recognitions add`. Do not hand-edit
   HITS, FIRST_SEEN, `INDEX.md` or `LEDGER.md`.

## Repository rules

- Python 3.10 or newer, standard library only. Do not install packages and do not add
  dependency manifests.
- Recognition files are printable ASCII with lines of 100 columns or fewer. The format is
  specified in `skills/mandragora-slops/.recognitions/FORMAT.md`.
- Scanner thresholds are named constants with a comment that explains the value.
- Keep `scanners/core.py` free of domain logic. Domain code lives in `scan_<domain>.py`,
  `references/<domain>.md` and `.recognitions/<domain>/`.
- Run `python skills/mandragora-slops/tests/run_tests.py` before you report work as done.
- Prose you add to this repository must pass the copy scanner:
  `python -m scanners.core scan <file> --domain copy --min-severity 3` exits 0.
