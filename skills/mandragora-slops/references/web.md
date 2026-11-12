# Web rubric (Layer B)

Layer A (`scanners/scan_web.py`) reads markup, Tailwind classes and CSS. This rubric covers what a
rule cannot see: composition, intent and coherence across the page. Use the files in
`.recognitions/web/` as few-shot examples while scoring.

## How to score

Score each row from 0 to 3 for the input under review.

| Score | Meaning |
|-------|---------|
| 0 | Absent. |
| 1 | Trace: one small instance outside the main content. |
| 2 | Clear: the pattern shapes a visible area of the page. |
| 3 | Dominant: the page depends on the pattern. |

Pass threshold: every row scores 0 or 1, and every row whose recognition has severity 4 or 5
scores 0. Report the total score next to the verdict. A slop element that fits no row goes to
step S5 as a learning candidate.

## Rows

| Row | Signal to judge | Recognition | A score of 3 looks like |
|-----|-----------------|-------------|-------------------------|
| W1 | The headline names no product noun, number or audience of its own | web-vague-verb-hero | Swapping in a competitor's name changes nothing |
| W2 | Features get equal space although they matter unequally | web-three-icon-feature-cards | Every feature is a same-size card with an icon tile |
| W3 | Color fields exist for mood only and carry no brand or data meaning | web-purple-blue-gradient-hero | The hero is a gradient with text floating on it |
| W4 | Emphasis comes from effects on letters instead of wording or structure | web-gradient-clipped-headline | Key words are readable only through a gradient fill |
| W5 | Translucent layers and blur stand in for hierarchy | web-glassmorphism-card | Panels need blobs behind them to be visible at all |
| W6 | Elevation has no layer logic: everything floats at the same height | web-rounded-shadow-everywhere | Inputs, cards and sections share one radius and shadow |
| W7 | Type speaks with one voice for prose, data and labels | web-single-sans-no-hierarchy | Prices, labels and body text differ by size only |
| W8 | Social proof cannot be verified: no named person, no source | web-trusted-by-logo-strip | A logo row of invented or anonymous brands |
| W9 | AI features are labeled by a magic metaphor instead of their output | web-sparkles-ai-icon | Every AI button carries the same sparkle or wand |
| W10 | Lighting effects appear without any light source in the layout | web-neon-glow-dark | Halos on cards, buttons and inputs at once |
| W11 | Grid sizes follow a template, not the content inside each cell | web-default-bento-grid | Short text in large tiles, dense charts in small ones |
| W12 | One status is encoded by several carriers at once | web-pill-dot-outline-badge | Shape, dot, outline and tint all say the same word |

## Notes for judges

- Judge the rendered intent, not only the code. A gradient defined in a theme file still counts
  when it ends up behind the hero.
- Layer A wins on presence. If a rule fired, the row scores at least 1 even when the element
  looks minor in context.
- Mark which rows drove the verdict so the redesign step knows which transformations to apply.
