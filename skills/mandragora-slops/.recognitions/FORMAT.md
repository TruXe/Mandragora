# Recognition file format

A recognition records one slop element that the skill knows how to spot and how to remove.
Each recognition is one file:

    .recognitions/<domain>/<id>.slop.txt

The files are the learning corpus. Any model can read them as few-shot examples without
tooling, so the format is plain, rigid and line oriented.

## Encoding rules

- Printable ASCII only: bytes 0x20 to 0x7E plus LF (0x0A). No tabs, no CR, no Unicode.
  Box drawing, emoji and curly quotes are not allowed, including inside the ASCII art.
- Every line is at most 100 columns.
- The file ends with exactly one LF.
- No blank lines outside the two ASCII fences.
- The file name is the ID plus `.slop.txt`, and the parent folder is the DOMAIN.

## Sections

All fourteen sections appear exactly once, in this order. Section headers start at column 0.

| Section | Form | Content |
|---------|------|---------|
| ID | inline | `<domain>-<kebab-slug>`, unique and stable. Never renamed once published. |
| DOMAIN | inline | `web`, `app`, `tui`, `texture`, `model3d` or `copy` (or a newly added domain). |
| NAME | inline | Short human name, 3 to 80 characters. |
| SEVERITY | inline | `1` (minor tell) to `5` (instant AI giveaway). |
| SIGNATURE | inline | Normalized one-line fingerprint used for dedupe (see below). |
| SIGNALS | block | At least two bullets of observable features, each `  - ` plus at least four words. |
| STATIC_RULES | inline | Comma separated scanner rule ids, or exactly `none (rubric only)`. |
| WHY | block | One to three sentences on why the element reads as machine generated. |
| ASCII_SLOP | fenced | ASCII depiction of the slop element. |
| FIX | block | The concrete transformation that removes the signals. |
| ASCII_FIXED | fenced | ASCII depiction of the corrected element. |
| SOURCE | inline | `seed` (shipped with the skill) or `learned` (added by a run). |
| FIRST_SEEN | inline | `unseen`, or the YYYY-MM-DD date written by the script at run time. |
| HITS | inline | Non-negative integer, raised by one each time a run matches the recognition. |

Forms:

- inline: `KEY: value` on one line.
- block: `KEY:` alone on its line, then one or more lines indented by two spaces. SIGNALS
  lines are bullets (`  - text`); a bullet may continue on lines indented by four spaces.
- fenced: `KEY:` alone on its line, then the opening fence line, the art, and the line
  `+--END--`. The opening fence is `+--SLOP--` for ASCII_SLOP and `+--FIXED--` for
  ASCII_FIXED. Art lines are free form ASCII; blank lines inside a fence are kept.

## Signature

The signature is the dedupe key. Two recognitions with the same normalized signature are the
same element, whatever their IDs or wording.

    <domain>|<element>|<feature>+<feature>+...

Normalization (applied by `scanners/recognitions.py`): lowercase; spaces, underscores and
slashes become `-`; only `a-z 0-9 | + . -` remain; repeated dashes collapse; dashes next to
`|` or `+` are trimmed. A stored signature must already be in normalized form.

## Content rules

- SIGNALS describe what can be observed or measured: a class name, a CSS property, a pixel
  statistic, a mesh property, a phrase. Feelings such as "looks generic" are rejected by the
  validator.
- FIX changes the structure or the signal carrier. A recolor or a rename of the same pattern
  is not a fix, and the validator rejects a FIX without a structural verb.
- ASCII_FIXED must differ from ASCII_SLOP.
- Art by domain: web, app and tui draw the layout; texture draws a luminance sample with
  the ramp ` .:-=+*#%@` (dark to bright); model3d draws an orthographic wireframe or
  silhouette.

## Runtime fields

SOURCE, FIRST_SEEN and HITS are owned by the scripts:

- Seeds ship with `FIRST_SEEN: unseen` and `HITS: 0`.
- `python -m scanners.core scan <path> --record` and `python -m scanners.recognitions hit <id>`
  raise HITS by one and replace `unseen` with the current date on the first match.
- `python -m scanners.recognitions add <draft>` writes learned files with `SOURCE: learned`,
  `FIRST_SEEN` set to the current date and `HITS: 1`. A draft whose signature already exists
  raises the existing file's HITS instead of creating a new file.

Dates are always computed when the script runs. No file carries a hand-written date.

## Example

    ID: web-pill-dot-outline-badge
    DOMAIN: web
    NAME: Pill status badge with inner dot and matching outline
    SEVERITY: 4
    SIGNATURE: web|status-badge|pill-shape+inner-dot+outline-matches-dot
    SIGNALS:
      - Fully rounded pill container (rounded-full or border-radius >= 50px)
      - Small 6 to 10 px colored circle placed before the label inside the pill
    STATIC_RULES: web.pill-dot-outline-badge
    WHY:
      Three status carriers say the same thing at once.
    ASCII_SLOP:
    +--SLOP--
     ( * Active )
    +--END--
    FIX:
      Keep one carrier: plain text with a subtle tint, and drop the dot and the outline.
    ASCII_FIXED:
    +--FIXED--
     Active
    +--END--
    SOURCE: seed
    FIRST_SEEN: unseen
    HITS: 0

(The example above is shortened. Library files follow every rule in this document.)
