---
name: mandragora-slops
description: Detect AI slop (generic, templated, instantly recognizable AI output) in web design, app UI, terminal UI, textures, 3D models and UI copy, record every recognized element in an ASCII recognition library, then produce a NO-AI-SLOP redesign and re-scan it until clean. Use whenever the user says detect AI slop, slop check, anti slop, no AI look, de-slop, make it not look AI generated, najdi AI slop, nesmi to vypadat AI, odslopuj, zkontroluj slop, or asks to review HTML, CSS, JSX, Tailwind, Vue, Svelte, Blade, SwiftUI, Compose, XAML, Flutter, QML or ImGui screens, CLI output, PNG textures, OBJ or glTF meshes, or marketing and UI text for generic AI patterns.
---

# Mandragora slops

This skill finds AI slop in six domains (web, app, tui, texture, model3d, copy), names each
element with a recognition id from the library in `.recognitions/`, adds new elements to that
library, and rewrites the input into a version without the slop signals.

Two layers do the detection:

- Layer A: deterministic scanners in `scanners/` (Python standard library, no installs).
- Layer B: your judgment, scored against `references/<domain>.md` with the recognition files as
  few-shot examples.

Run every command from this skill folder (the folder that holds this file). Python 3.10 or newer
is required. Do not install packages.

## Workflow

Follow these steps in order on every use.

### S1 Identify the domain

Detect the domain of each input file:

```
python -m scanners.core detect <path>
```

Confirm with the user only when the result is `unknown` or the file mixes domains in a way that
changes the answer (for example an HTML page whose main content is marketing text). Web pages
usually need two passes: `web` for the design and `copy` for the text. Desktop and mobile UI
code is `app`; HTML app shells (Electron, Tauri) are scanned with `--domain app`.

### S2 Run Layer A

```
python -m scanners.core scan <path> --json
python -m scanners.core scan <path> --domain web,copy --json
```

Exit code 0 means no findings, 1 means findings, 2 means an error (read the `errors` field).
Each finding carries `rule_id`, `recognition_id`, `severity`, `location`, `evidence` and
`confidence`. Folders are scanned recursively.

### S3 Run Layer B

1. Read `references/<domain>.md` for the scoring scale, the rows and the pass threshold.
2. Read the recognition files in `.recognitions/<domain>/` that Layer A matched, plus the
   rubric-only ones (`STATIC_RULES: none (rubric only)`), as few-shot examples.
3. Score every rubric row from 0 to 3 for the input and note the location and evidence for each
   row above 0.

### S4 Report findings

Merge both layers into one table, highest severity first:

| Recognition | Severity | Layer | Location | Evidence |
|-------------|----------|-------|----------|----------|

Layer A wins on conflicts about presence: when a rule fired, the element is present even if it
looks minor to you. Layer B may add elements that Layer A cannot see. State the rubric verdict
(pass or fail) and the total score under the table.

### S5 Learn

- For every matched existing recognition, raise its hit counter once per run:

  ```
  python -m scanners.recognitions hit <recognition-id> [<recognition-id> ...]
  ```

- For every slop element that matches no recognition, write a draft and add it:

  ```
  python -m scanners.recognitions template <domain> > draft.slop.txt
  python -m scanners.recognitions add draft.slop.txt --source <input-path> --reason "<one line>"
  ```

  The command validates the format, dedupes by SIGNATURE (a duplicate raises HITS of the
  existing file instead of creating one), appends `.recognitions/LEDGER.md` and rebuilds
  `.recognitions/INDEX.md`. It fills SOURCE, FIRST_SEEN and HITS itself. SIGNALS must be
  observable (class names, property values, measurements, phrases); the validator rejects vague
  wording such as "looks generic". Use `STATIC_RULES: none (rubric only)` unless you also add a
  scanner rule.

Never edit HITS, FIRST_SEEN or LEDGER rows by hand.

### S6 Redesign

1. Apply `references/redesign-playbook.md` and the FIX section of each matched recognition.
   Change the structure or the signal carrier; a recolor or rename is a failed redesign.
2. Write the redesign next to the input as `<name>.noslop.<ext>` unless the user asked for an
   in-place edit. Use real content from the input; mark missing facts instead of inventing them.
3. Render it as ASCII and include the render in your answer:

   ```
   python -m scanners.ascii_render <redesign-path> --width 80
   ```

   Web and app files render as layout boxes (HTML, JSX, Vue, Svelte, XAML, SwiftUI, Compose). For
   other toolkits (Flutter, QML, ImGui) write a JSON layout spec and render that file. Textures
   render as a luminance ramp, meshes as orthographic wireframes, copy as reflowed text.

For textures and meshes the redesign is a written spec (what to repaint, rebake, retopologize or
re-unwrap, with numbers) plus the ASCII depiction, unless the user provided tools to edit the asset.

### S7 Verify

Re-run Layer A on the redesign and score Layer B again:

```
python -m scanners.core scan <redesign-path> --min-severity 3
```

Repeat S6 until Layer A exits 0 at severity 3 and every rubric row scores 0 or 1. Stop after
three rounds. Report any residual finding with its recognition id and the reason it remains.

## JSON layout spec

Nodes have a `type` and optional `text`, `title`, `level` and `children`. Types: `col`, `row`,
`box`, `heading`, `text`, `button`, `input`, `image`, `rule`.

```json
{"type": "box", "title": "Billing", "children": [
  {"type": "heading", "text": "Invoices"},
  {"type": "row", "children": [{"type": "text", "text": "Invoice 1042"},
                               {"type": "button", "text": "Pay"}]}]}
```

## Adding a domain

A new domain needs these files and nothing else:

1. `.recognitions/<domain>/` with seed recognitions that follow `.recognitions/FORMAT.md`.
2. `references/<domain>.md` with the rubric rows for the domain.
3. `scanners/scan_<domain>.py` that calls `register_domain(...)` and decorates checks with
   `@rule("<domain>.<slug>", recognition="<domain>-<slug>", severity=N)`.
4. `tests/fixtures/<domain>/slop/<recognition-id>.<ext>` and
   `tests/fixtures/<domain>/clean/<recognition-id>.<ext>` for every recognition with a rule.

The core discovers `scan_*.py` modules on its own. Run `python tests/run_tests.py` to confirm.

## Files

- `scanners/core.py`: Finding model, rule registry, domain detection, scan CLI.
- `scanners/scan_<domain>.py`: rules per domain, thresholds as named constants.
- `scanners/recognitions.py`: library validation, dedupe, `add`, `hit`, index rebuild.
- `scanners/ascii_render.py`: ASCII renders for S6.
- `scanners/png_reader.py`, `scanners/mesh_reader.py`: PNG, OBJ and glTF readers.
- `.recognitions/`: the recognition library (`FORMAT.md`, `INDEX.md`, `LEDGER.md`).
- `references/`: rubrics per domain and the redesign playbook.
- `tests/`: fixtures and the unittest suite.
