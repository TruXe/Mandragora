# Texture rubric (Layer B)

Layer A (`scanners/scan_texture.py`) measures pixel statistics: wrap seams, repeat periods,
mirror correlation, lighting gradients, saturation, clipping and detail density. This rubric
judges what statistics miss: physical plausibility and the story of the material. Use the files
in `.recognitions/texture/` as few-shot examples. Look at the image at 100 percent and tiled 3x3.

## How to score

| Score | Meaning |
|-------|---------|
| 0 | Absent. |
| 1 | Trace: visible only up close or in one corner. |
| 2 | Clear: visible at normal viewing distance on a surface. |
| 3 | Dominant: the defect is the first thing a viewer sees. |

Pass threshold: every row scores 0 or 1, and every row whose recognition has severity 4 or 5
scores 0. Report the total. A slop element that fits no row goes to step S5.

## Rows

| Row | Signal to judge | Recognition | A score of 3 looks like |
|-----|-----------------|-------------|-------------------------|
| X1 | Tiling reveals edges where copies meet | texture-visible-tiling-seam | A grid of lines across a tiled wall |
| X2 | A feature repeats at a spacing the eye picks up | texture-short-repeat-period | The same knot marching across every plank |
| X3 | Shading has a direction that belongs to a photo, not a material | texture-baked-lighting-albedo | One side bright, the other dark, in the albedo |
| X4 | Detail exists at one scale only and color is pushed | texture-oversaturated-uniform-noise | Bright static with no large forms |
| X5 | Features appear in mirrored pairs | texture-mirror-symmetry | Cracks reflected across a center line |
| X6 | Structure stops making physical sense up close | texture-diffusion-micro-detail | Bricks melting into each other, letters that are not letters |
| X7 | Shine is identical everywhere | texture-flat-roughness | Worn edges and dirt with the same gloss as clean areas |
| X8 | Values sit at pure black or pure white | texture-histogram-clipping | Flat patches with no detail in shadows or highlights |
| X9 | Wear ignores use: detail spreads evenly edge to edge | texture-uniform-detail-density | Scratches equally dense in corners and in the center |

## Notes for judges

- X6 has no static rule. Zoom to individual units (bricks, planks, rivets) and ask whether a
  person could have built or worn them that way.
- Check the full material set when it exists: albedo, roughness, normal and height should agree
  about where wear happened.
- Layer A wins on presence: a fired rule means the row scores at least 1.
