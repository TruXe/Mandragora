# Redesign playbook

Step S6 uses this playbook to turn a finding into a NO-AI-SLOP version. Each family lists the
transformations that remove the signal. A redesign must change the structure or the carrier of
the signal. Changing a hue, renaming a class or swapping one icon set for another while the
pattern stays in place is a failed redesign, and step S7 treats it as a residual finding.

General order of work:

1. Read the FIX section of every matched recognition; it is the minimum change.
2. Apply the family transformation below, choosing one option per element.
3. Replace placeholder content with real content (names, numbers, product nouns) or mark the
   gap for the user instead of inventing data.
4. Render the result with `python -m scanners.ascii_render <file>` and re-scan it.

## Web and app

### Status carriers

Recognitions: `web-pill-dot-outline-badge`, `app-pill-dot-status-chip`.

Choose one carrier for the state:

- plain text in the status color with no container, placed in an aligned column;
- a square chip with a subtle tint and no dot and no outline;
- one sharp icon from the product's own set followed by the word.

Remove the other carriers entirely. A pill recolored to gray with its dot and outline kept is a
failed redesign; the scanner flags neutral pills too.

### Color fields

Recognitions: `web-purple-blue-gradient-hero`, `app-purple-gradient-header`,
`web-glassmorphism-card`, `app-glass-acrylic-panel`, `web-neon-glow-dark`,
`app-neon-glow-controls`.

- Replace decorative gradients with a flat surface, and move color to one accent element that
  marks the primary action or one data point.
- Replace blur and translucency with opaque surfaces separated by spacing, a 1px rule or one
  value step.
- Remove glows; distinguish the primary control by fill and placement. Keep a single visible
  focus ring for keyboard users.
- Delete background blobs that only existed to make blur or glow visible.

### Hierarchy and type

Recognitions: `web-vague-verb-hero`, `web-gradient-clipped-headline`,
`web-single-sans-no-hierarchy`.

- Rewrite the headline as a concrete claim with a product noun and a number. Keep one action.
- Put proof beside the claim: a screenshot, a sample output, a named quote.
- Set emphasis through wording and weight, never through gradient fills on letters.
- Pair two families with distinct jobs (display or serif for headlines, mono or tabular figures
  for data) and add an uppercase label style for metadata.

### Repetition and grids

Recognitions: `web-three-icon-feature-cards`, `web-default-bento-grid`,
`app-identical-tile-grid`, `app-uniform-corner-radius`, `web-rounded-shadow-everywhere`.

- Rank content before laying it out. Give the first item a full row with real media; list the
  rest as text rows or a table.
- Size grid cells from their content, drop fixed row heights, and vary gaps to group items.
- Assign radius and elevation by role: small radius for controls, none for lists and panels,
  elevation only for layers that sit above the page (menus, dialogs).
- Remove icon tiles that repeat the title in picture form.

### Proof and greetings

Recognitions: `web-trusted-by-logo-strip`, `app-greeting-stat-dashboard`.

- Remove placeholder logo strips. Keep one named proof point with a source, or nothing.
- Replace greetings with the task the user came for, and state every delta with its baseline
  and period.

### Iconography and navigation

Recognitions: `web-sparkles-ai-icon`, `app-sparkle-ai-action`, `app-five-tab-generic-bar`.

- Name AI actions by their output (Summarize thread, Draft reply) and draw the output if an icon
  is needed.
- Build navigation from the destinations that exist; put creation inside the screen where the
  object lives.

## TUI

Recognitions: `tui-emoji-title-box-frames`, `tui-centered-double-banner`,
`tui-ascii-logo-every-command`, `tui-boxed-key-value-table`, `tui-rainbow-ansi`,
`tui-emoji-status-markers`, `tui-exclamation-success`, `tui-fake-progress`.

- Remove frames, banners and logos from command output. Show the name and version in `--help`
  and `--version` only.
- Print key and value data as aligned `key: value` lines and offer `--json` for scripts.
- Limit color to meaning: one color for errors, a dim style for metadata, default for the rest.
  The output must read the same with `NO_COLOR` set.
- Replace emoji markers with fixed-width words (`ok`, `warn`, `fail`) in a leading column.
- Replace cheer with the result: counts, paths, identifiers, durations.
- Drive progress from real totals (files, bytes, items) or print one line per finished step.

## Texture

Recognitions: `texture-visible-tiling-seam`, `texture-short-repeat-period`,
`texture-mirror-symmetry`, `texture-baked-lighting-albedo`, `texture-histogram-clipping`,
`texture-oversaturated-uniform-noise`, `texture-uniform-detail-density`,
`texture-diffusion-micro-detail`, `texture-flat-roughness`.

- Tiling: offset by half, repaint across the seam, verify with a 3x3 tile. Author detail at the
  full tile size instead of stamping a smaller patch; break mirrors by repainting one half.
- Light: remove the low-frequency luminance trend from albedo and move occlusion to its own map.
  Remap values into the plausible albedo range and recover clipped detail.
- Detail: layer large forms, medium breakup and fine grain; reduce saturation toward measured
  values. Drive wear with masks for edges, contact points and runoff.
- Structure: rebuild repeating units (bricks, planks) from explicit rules and add generated
  detail only inside each unit. Remove pseudo text.
- PBR: derive roughness from the material's history, as its own map.

## 3D model

Recognitions: `model3d-non-manifold-edges`, `model3d-flipped-normals`, `model3d-triangle-soup`,
`model3d-melted-topology`, `model3d-uniform-bevel-width`, `model3d-perfect-symmetry`,
`model3d-uniform-over-subdivision`, `model3d-floating-parts`, `model3d-default-material-only`,
`model3d-uv-stretch`, `model3d-uv-shattered-islands`.

- Topology: weld by distance, delete fins and internal faces, recalculate normals from one seed
  face, retopologize melted areas with quads that follow the form, and restore creases.
- Form: vary bevel width per edge group by function and wear; break mirror symmetry after
  mirroring; collapse coplanar loops and keep density only where the silhouette curves.
- Assembly: delete stray fragments and seat every part with real contact or joint geometry.
- Surface: split faces into named material slots by physical part; re-unwrap with planned seams
  along hidden edges, relax islands for even texel density, then pack.

## Copy

Recognitions: `copy-hype-vocabulary`, `copy-empty-superlatives`, `copy-dash-connector`,
`copy-rule-of-three`, `copy-negative-parallelism`, `copy-question-reveal`,
`copy-fast-paced-world-opener`, `copy-whether-you-are-hedge`, `copy-ready-to-get-started`,
`copy-sycophantic-opener`, `copy-emoji-bullets`, `copy-title-case-headings`.

- Replace each hype word or superlative with the action, object and number it hides; cut the
  sentence when nothing concrete remains.
- Split dashed sentences into separate sentences or use a colon before an explanation.
- Keep the one true item of a triplet and state its number.
- State claims directly; drop the negated half and the staged question.
- Start with the first concrete fact; end with the last useful fact or one specific next step.
- Pick the reader and write to their situation.
- Use plain bullets and sentence case headings.

## Verification

A redesign is done when `python -m scanners.core scan <redesign> --min-severity 3` exits 0 and
every rubric row scores 0 or 1. Stop after three redesign rounds and report what remains, with
the recognition id and the reason it could not be removed (missing real data, a brand rule, a
platform constraint).
