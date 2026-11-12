# 3D model rubric (Layer B)

Layer A (`scanners/scan_model3d.py`) checks topology, winding, components, bevel widths,
symmetry, face density, materials and UVs. This rubric judges form and craft: whether the model
reads as designed, built and used. Use the files in `.recognitions/model3d/` as few-shot
examples. Look at the silhouette from three sides, then at wireframe and UV views.

## How to score

| Score | Meaning |
|-------|---------|
| 0 | Absent. |
| 1 | Trace: one small part or a hidden area. |
| 2 | Clear: visible in a normal camera shot or a standard export check. |
| 3 | Dominant: the asset cannot ship without rework. |

Pass threshold: every row scores 0 or 1, and every row whose recognition has severity 4 or 5
scores 0. Report the total. A slop element that fits no row goes to step S5.

## Rows

| Row | Signal to judge | Recognition | A score of 3 looks like |
|-----|-----------------|-------------|-------------------------|
| M1 | Edge treatment ignores function and wear | model3d-uniform-bevel-width | The same rim on handles, joints and protected edges |
| M2 | Organic or worn forms are exactly mirrored | model3d-perfect-symmetry | Matching chips on both sides of a rock or face |
| M3 | Geometry has no clear inside and outside | model3d-non-manifold-edges | Fins and internal walls left from merges |
| M4 | Surface orientation flips between neighbors | model3d-flipped-normals | Black stripes or holes with backface culling |
| M5 | Triangles are unconnected | model3d-triangle-soup | Faceted shading everywhere, nothing welds |
| M6 | Polygon budget spent where the silhouette is flat | model3d-uniform-over-subdivision | Flat walls as dense as curved parts |
| M7 | Parts do not touch what they should hold | model3d-floating-parts | A handle hovering over a lid |
| M8 | Hard forms read soft and melted | model3d-melted-topology | Box corners as rounded blobs, random triangles |
| M9 | Materials were never assigned by part | model3d-default-material-only | One default slot for wood, metal and rubber |
| M10 | Texture space is uneven across the surface | model3d-uv-stretch | Checker squares smeared on some faces, tiny on others |
| M11 | Seams have no plan | model3d-uv-shattered-islands | An atlas of single-face islands |

## Notes for judges

- Ask what the object is made of and how it was assembled; the answer should be visible in the
  topology (support loops at joints, separate parts for separate materials).
- Scale matters: compare bevel widths and detail size to a human-sized reference.
- Layer A wins on presence: a fired rule means the row scores at least 1.
