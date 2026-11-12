# TUI rubric (Layer B)

Layer A (`scanners/scan_tui.py`) parses ANSI color codes, box drawing, progress output and status
lines. This rubric judges whether terminal output serves a person reading it and a script piping
it. Use the files in `.recognitions/tui/` as few-shot examples.

## How to score

| Score | Meaning |
|-------|---------|
| 0 | Absent. |
| 1 | Trace: one decorated line in otherwise plain output. |
| 2 | Clear: a command's normal output follows the pattern. |
| 3 | Dominant: every command of the tool follows the pattern. |

Pass threshold: every row scores 0 or 1, and every row whose recognition has severity 4 or 5
scores 0. Report the total. A slop element that fits no row goes to step S5.

## Rows

| Row | Signal to judge | Recognition | A score of 3 looks like |
|-----|-----------------|-------------|-------------------------|
| T1 | Frames wrap content that would read fine as plain lines | tui-emoji-title-box-frames | Every block boxed, emoji in each frame title |
| T2 | Color carries no meaning that survives NO_COLOR | tui-rainbow-ansi | Each word gets its own color, errors do not stand out |
| T3 | Output opens with ceremony before the first fact | tui-centered-double-banner | A centered title box on every run |
| T4 | Progress output is not tied to measurable work | tui-fake-progress | Bars step 20, 40, 60 on a timer; spinners say Thinking |
| T5 | Status depends on pictographs instead of words | tui-emoji-status-markers | Check marks and rockets as the only status column |
| T6 | Tables are drawn where aligned lines would do | tui-boxed-key-value-table | Two-column key and value data inside a full grid |
| T7 | Branding repeats where results should be | tui-ascii-logo-every-command | A figlet logo above each command's output |
| T8 | Completion lines cheer instead of reporting | tui-exclamation-success | `Success!` with no count, path or duration |

## Notes for judges

- Pipe test: imagine `tool | grep error` and `tool > log.txt`. Decoration that breaks either
  raises T1, T2, T5 or T6.
- Check `--help`: generated CLIs often print flag tables with emoji headers and ASCII logos.
- Layer A wins on presence: a fired rule means the row scores at least 1.
