# App rubric (Layer B)

Layer A (`scanners/scan_app.py`) reads XAML, SwiftUI, Compose, Flutter, QML, ImGui and HTML app
shells. This rubric judges screen composition and intent that code patterns cannot show. Use the
files in `.recognitions/app/` as few-shot examples, and the web rubric for HTML-based apps.

## How to score

| Score | Meaning |
|-------|---------|
| 0 | Absent. |
| 1 | Trace: one small instance on a secondary screen or state. |
| 2 | Clear: the pattern shapes a main screen. |
| 3 | Dominant: the app's identity depends on the pattern. |

Pass threshold: every row scores 0 or 1, and every row whose recognition has severity 4 or 5
scores 0. Report the total. A slop element that fits no row goes to step S5.

## Rows

| Row | Signal to judge | Recognition | A score of 3 looks like |
|-----|-----------------|-------------|-------------------------|
| A1 | Corner radius does not follow the role of the surface | app-uniform-corner-radius | Fields, cards, sheets and images share one radius |
| A2 | The home screen has no entry point: all metrics weigh the same | app-identical-tile-grid | A grid of equal tiles with icon, number and delta |
| A3 | The header carries color for mood instead of context | app-purple-gradient-header | A violet to blue band with a greeting on it |
| A4 | Status is stated by capsule, dot and outline together | app-pill-dot-status-chip | Every list row ends in the same three-carrier chip |
| A5 | Transparency replaces structure between layers | app-glass-acrylic-panel | Frosted panels stacked over a photo or gradient |
| A6 | The AI action is named by a metaphor, not by its result | app-sparkle-ai-action | A floating sparkle button labeled with the word AI |
| A7 | Light effects appear on controls with no light logic | app-neon-glow-controls | Several buttons glow in different hues |
| A8 | The best screen space goes to politeness instead of the task | app-greeting-stat-dashboard | A large greeting over delta tiles with no period |
| A9 | Navigation skeleton copied before the destinations exist | app-five-tab-generic-bar | Five tabs where two lead to empty or duplicate screens |

## Notes for judges

- Check platform conventions: a native Windows app copying an iOS tab bar, or an Android app
  with SwiftUI style capsules, raises A1, A4 and A9.
- Score empty, loading and error states too; generated apps often leave them as default text.
- Layer A wins on presence: a fired rule means the row scores at least 1.
