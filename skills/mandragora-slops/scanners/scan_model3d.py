"""3D model domain: meshes from OBJ, glTF (.gltf with embedded or sidecar
buffers) and GLB.

The loader welds coincident vertices, builds the edge map, face normals and
areas, and connected components. Rules read topology (manifold, winding,
components), geometry statistics (bevel widths, symmetry, dihedral angles,
face sizes) and surface data (materials, UVs).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from scanners.core import ScanError, hit, register_domain, rule
from scanners.mesh_reader import (MeshError, bbox, cross, diagonal, dot, newell_normal, norm,
                                  read_mesh, sub)

DOMAIN = "model3d"
EXTENSIONS = (".obj", ".gltf", ".glb")

# ---------------------------------------------------------------- thresholds
# Vertices closer than this share of the bounding diagonal are one vertex.
WELD_REL_TOL = 1e-6
# Open edges up to this share of all edges are holes in a closed mesh. Above
# it the mesh is intentionally open (a plane, cloth, a card).
HOLE_MAX_RATIO = 0.10
# Triangle soup: share of faces sharing no vertex index with any other face,
# minimum face count, and share of raw vertices that welding would remove.
SOUP_ISOLATED_MIN = 0.90
SOUP_MIN_FACES = 8
SOUP_DUPLICATE_MIN = 0.40
# Bevel strips: quads at least this elongated, meeting both long neighbors at
# a chamfer angle. Eight equal strips (CV of width <= 5%) is a one-click bevel.
BEVEL_MIN_ASPECT = 4.0
BEVEL_ANGLE_RANGE = (20.0, 70.0)
BEVEL_MIN_STRIPS = 8
BEVEL_MAX_CV = 0.05
# A chamfer strip runs beside a face at least this many times its own area.
# Cylinder side quads only touch equal quads, so they are not mistaken for strips.
BEVEL_NEIGHBOR_AREA_RATIO = 2.0
# Symmetry: mirrored vertex must land within this share of the diagonal, for
# at least SYM_MATCH_MIN of all vertices, on meshes with enough vertices.
SYM_TOL_REL = 1e-4
SYM_MATCH_MIN = 0.995
SYM_MIN_VERTS = 30
# Organic shape without a name hint: share of edges smoother than the angle.
ORGANIC_SMOOTH_MIN = 0.70
ORGANIC_SMOOTH_DEG = 25.0
ORGANIC_MIN_FACES = 60
# Over-subdivision: many faces, most interior edges coplanar, uniform sizes.
OVERSUB_MIN_FACES = 200
COPLANAR_DEG = 0.5
OVERSUB_COPLANAR_MIN = 0.50
OVERSUB_AREA_CV_MAX = 0.35
# Floating part: gap to the main part above this share of the diagonal.
FLOAT_GAP_REL = 0.01
GAP_SAMPLE = 400
# Melted image-to-3D topology: dense triangle-only mesh without sharp edges
# and with irregular vertex valence or many sliver triangles.
MELT_MIN_FACES = 200
SHARP_DEG = 35.0
MELT_SHARP_MAX = 0.005
MELT_VALENCE_STD_MIN = 0.6
SLIVER_DEG = 10.0
MELT_SLIVER_MIN = 0.10
# Default material check starts at this many faces (tiny helpers are exempt).
DEFAULT_MAT_MIN_FACES = 12
# UV stretch: std of log2(UV area / 3D area) and share of faces off by 4x.
UV_MIN_FACES = 8
UV_LOG_STD_MAX = 1.0
UV_OUTLIER_LOG2 = 2.0
UV_OUTLIER_FRAC = 0.20
# Shattered UVs: islands per face above this ratio on meshes with enough faces.
UV_ISLAND_RATIO_MAX = 0.50
UV_ISLAND_MIN_FACES = 24
# Quadify: triangles merged into quads across coplanar diagonals.
QUADIFY_DEG = 1.0

ORGANIC_NAME_RE = re.compile(
    r"rock|stone|boulder|pebble|cliff|tree|trunk|branch|root|log\b|stump|leaf|plant|bush|skull|"
    r"bone|face|head|body|creature|monster|character|hand|torso|organic|wood|mushroom|coral|"
    r"shell|terrain|cave|ruin|worn|damaged|weathered", re.I)
DEFAULT_MATERIAL_RE = re.compile(
    r"^(|none|null|default|defaultmaterial|default[_ ]material|material|mat|lambert\d*|blinn\d*|"
    r"phong\d*|initialshadinggroup|standardsurface\d*|untitled|no[_ ]?material|wire_\d+|"
    r"material[._ ]?\d*|mat[._ ]?\d+)$", re.I)


@dataclass
class ModelDoc:
    path: Path
    mesh: object
    verts: list
    faces: list
    face_src: list
    remap: list
    diag: float
    normals: list = field(default_factory=list)
    areas: list = field(default_factory=list)
    edges: dict = field(default_factory=dict)
    comp: list = field(default_factory=list)

    def dihedral(self, key) -> float | None:
        """Angle between the two faces on an edge in degrees (0 = coplanar)."""
        users = self.edges.get(key)
        if not users or len(users) != 2:
            return None
        (f1, d1), (f2, d2) = users
        n1, n2 = self.normals[f1], self.normals[f2]
        c = dot(n1, n2)
        if d1 == d2:          # inconsistent winding: compare as if fixed
            c = -c
        return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _find(parent, i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union(parent, a, b):
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def analyse(mesh, path: Path) -> ModelDoc:
    if not mesh.positions or not mesh.faces:
        raise ScanError(f"{path.name}: mesh has no faces")
    diag = diagonal(mesh.positions) or 1.0
    tol = diag * WELD_REL_TOL
    table, verts, remap = {}, [], []
    for p in mesh.positions:
        key = (round(p[0] / tol), round(p[1] / tol), round(p[2] / tol))
        idx = table.get(key)
        if idx is None:
            idx = table[key] = len(verts)
            verts.append(p)
        remap.append(idx)
    faces, face_src = [], []
    for fi, f in enumerate(mesh.faces):
        w = [remap[i] for i in f]
        w = [v for i, v in enumerate(w) if v != w[i - 1]]
        if len(set(w)) >= 3:
            faces.append(w)
            face_src.append(fi)
    doc = ModelDoc(path, mesh, verts, faces, face_src, remap, diag)
    for f in faces:
        n = newell_normal([verts[i] for i in f])
        length = norm(n)
        doc.areas.append(length / 2.0)
        doc.normals.append((n[0] / length, n[1] / length, n[2] / length) if length > 0 else
                           (0.0, 0.0, 0.0))
    for fi, f in enumerate(faces):
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            doc.edges.setdefault((min(a, b), max(a, b)), []).append((fi, a < b))
    parent = list(range(len(verts)))
    for f in faces:
        for v in f[1:]:
            _union(parent, f[0], v)
    doc.comp = [_find(parent, f[0]) for f in faces]
    return doc


def load(path: Path) -> ModelDoc:
    try:
        mesh = read_mesh(path)
    except MeshError as exc:
        raise ScanError(str(exc)) from exc
    return analyse(mesh, path)


def sniff(path: Path, head: bytes) -> int:
    ext = path.suffix.lower()
    if ext == ".obj":
        return 90 if re.search(rb"(^|\n)\s*v\s", head) else 30
    if ext == ".gltf":
        return 90
    if ext == ".glb":
        return 90 if head[:4] == b"glTF" else 30
    return 0


register_domain(DOMAIN, load=load, sniff=sniff, extensions=EXTENSIONS,
                description="3D meshes: OBJ, glTF, GLB")


# --------------------------------------------------------------------------
# Analysis helpers
# --------------------------------------------------------------------------

def _mean_std(values):
    n = len(values)
    if not n:
        return 0.0, 0.0
    m = sum(values) / n
    return m, math.sqrt(sum((v - m) ** 2 for v in values) / n)


def interior_dihedrals(doc: ModelDoc) -> list:
    out = []
    for key, users in doc.edges.items():
        if len(users) == 2:
            d = doc.dihedral(key)
            if d is not None:
                out.append(d)
    return out


def is_organic(doc: ModelDoc) -> tuple:
    names = " ".join(doc.mesh.names) + " " + doc.path.stem
    m = ORGANIC_NAME_RE.search(names)
    if m:
        return True, f"name hint '{m.group(0)}'"
    dih = interior_dihedrals(doc)
    if len(doc.faces) >= ORGANIC_MIN_FACES and dih:
        # Curved but smooth: flat coplanar edges belong to boxes, not organic forms.
        curved = sum(1 for d in dih if COPLANAR_DEG <= d < ORGANIC_SMOOTH_DEG) / len(dih)
        if curved >= ORGANIC_SMOOTH_MIN:
            return True, f"{100 * curved:.0f}% smoothly curved edges"
    return False, ""


def quadify(doc: ModelDoc) -> list:
    """Merge coplanar triangle pairs across their longest edge into quads."""
    merged, polys = set(), []
    for fi, f in enumerate(doc.faces):
        if fi in merged:
            continue
        if len(f) != 3:
            polys.append(f)
            continue
        best = None
        for i in range(3):
            a, b = f[i], f[(i + 1) % 3]
            ln = math.dist(doc.verts[a], doc.verts[b])
            if best is None or ln > best[0]:
                best = (ln, a, b, f[(i + 2) % 3])
        _, a, b, c = best
        users = doc.edges.get((min(a, b), max(a, b)), [])
        other = next((u for u, _ in users if u != fi), None)
        if other is not None and other not in merged and len(doc.faces[other]) == 3 and \
                len(users) == 2 and (doc.dihedral((min(a, b), max(a, b))) or 99) < QUADIFY_DEG:
            d = next(v for v in doc.faces[other] if v not in (a, b))
            merged.update((fi, other))
            polys.append([a, d, b, c])
        else:
            polys.append(f)
    return polys


def bevel_strips(doc: ModelDoc) -> list:
    """Widths of chamfer strips: thin quads meeting both long neighbors at 20..70 deg."""
    widths = []
    face_index = {tuple(f): i for i, f in enumerate(doc.faces)}
    for poly in quadify(doc):
        if len(poly) != 4:
            continue
        p = [doc.verts[i] for i in poly]
        s = [math.dist(p[i], p[(i + 1) % 4]) for i in range(4)]
        a, b = (s[0] + s[2]) / 2, (s[1] + s[3]) / 2
        width, length = min(a, b), max(a, b)
        if width <= 0 or length / width < BEVEL_MIN_ASPECT:
            continue
        n = newell_normal(p)
        ln = norm(n)
        if ln == 0:
            continue
        n = (n[0] / ln, n[1] / ln, n[2] / ln)
        long_edges = [(0, 1), (2, 3)] if a > b else [(1, 2), (3, 0)]
        mine = {face_index.get(tuple(poly))}
        angles, neighbor_areas = [], []
        for i, j in long_edges:
            u, v = poly[i], poly[j]
            for fi, _ in doc.edges.get((min(u, v), max(u, v)), []):
                if fi in mine or doc.areas[fi] == 0:
                    continue
                if set(doc.faces[fi]) <= set(poly):
                    continue
                c = abs(dot(n, doc.normals[fi]))
                angles.append(math.degrees(math.acos(max(-1.0, min(1.0, c)))))
                neighbor_areas.append(doc.areas[fi])
        strip_area = ln / 2.0
        if len(angles) >= 2 and all(BEVEL_ANGLE_RANGE[0] <= x <= BEVEL_ANGLE_RANGE[1]
                                    for x in angles) and \
                max(neighbor_areas) >= BEVEL_NEIGHBOR_AREA_RATIO * strip_area:
            widths.append(width)
    return widths


def symmetry(doc: ModelDoc):
    lo, hi = bbox(doc.verts)
    tol = doc.diag * SYM_TOL_REL
    keys = {(round(p[0] / tol), round(p[1] / tol), round(p[2] / tol)) for p in doc.verts}
    best = (0.0, None)
    for k, axis in enumerate("xyz"):
        c = (lo[k] + hi[k]) / 2
        matched = 0
        for p in doc.verts:
            q = list(p)
            q[k] = 2 * c - p[k]
            base = [round(v / tol) for v in q]
            if any((base[0] + (d if k == 0 else 0), base[1] + (d if k == 1 else 0),
                    base[2] + (d if k == 2 else 0)) in keys for d in (0, -1, 1)):
                matched += 1
        ratio = matched / len(doc.verts)
        if ratio > best[0]:
            best = (ratio, axis)
    return best


def valence_std(doc: ModelDoc) -> float:
    nbrs = [set() for _ in doc.verts]
    for a, b in doc.edges:
        nbrs[a].add(b)
        nbrs[b].add(a)
    vals = [len(n) for n in nbrs if n]
    return _mean_std(vals)[1]


def _tri_min_angle(p0, p1, p2) -> float:
    angles = []
    for a, b, c in ((p0, p1, p2), (p1, p2, p0), (p2, p0, p1)):
        u, v = sub(b, a), sub(c, a)
        nu, nv = norm(u), norm(v)
        if nu == 0 or nv == 0:
            return 0.0
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, dot(u, v) / (nu * nv))))))
    return min(angles)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

@rule("model3d.non-manifold", recognition="model3d-non-manifold-edges", severity=4)
def r_non_manifold(doc: ModelDoc):
    """Edges shared by more than two faces, or holes in an otherwise closed mesh."""
    over = [k for k, u in doc.edges.items() if len(u) > 2]
    open_ = [k for k, u in doc.edges.items() if len(u) == 1]
    if over:
        yield hit(f"edge v{over[0][0] + 1}-v{over[0][1] + 1}", f"{len(over)} edge(s) shared by 3+ "
                  "faces", 0.95)
    ratio = len(open_) / max(1, len(doc.edges))
    if open_ and ratio <= HOLE_MAX_RATIO:
        yield hit(f"edge v{open_[0][0] + 1}-v{open_[0][1] + 1}", f"{len(open_)} open edge(s) "
                  f"({100 * ratio:.1f}% of edges): holes in a closed surface", 0.85)


@rule("model3d.flipped-normals", recognition="model3d-flipped-normals", severity=4)
def r_flipped(doc: ModelDoc):
    """Faces wound against their neighbors, or a closed mesh turned inside out."""
    nf = len(doc.faces)
    orient = [None] * nf
    adj = [[] for _ in range(nf)]
    for users in doc.edges.values():
        if len(users) == 2:
            (f1, d1), (f2, d2) = users
            same = d1 == d2   # same traversal direction = inconsistent pair
            adj[f1].append((f2, same))
            adj[f2].append((f1, same))
    minority = 0
    for start in range(nf):
        if orient[start] is not None:
            continue
        orient[start] = False
        stack, members = [start], [start]
        while stack:
            f = stack.pop()
            for g, same in adj[f]:
                want = (not orient[f]) if same else orient[f]
                if orient[g] is None:
                    orient[g] = want
                    stack.append(g)
                    members.append(g)
        flipped = sum(1 for m in members if orient[m])
        minority += min(flipped, len(members) - flipped)
    if minority:
        yield hit(f"{minority} face(s)", f"{minority} of {nf} faces wound opposite to their "
                  "neighbors (flipped normals)", 0.9)
        return
    closed = all(len(u) == 2 for u in doc.edges.values())
    if closed:
        vol = 0.0
        for f in doc.faces:
            p0 = doc.verts[f[0]]
            for i in range(1, len(f) - 1):
                vol += dot(p0, cross(doc.verts[f[i]], doc.verts[f[i + 1]])) / 6.0
        if vol < 0:
            yield hit("whole mesh", f"closed mesh with negative volume {vol:.3g}: every normal "
                      "points inward", 0.9)


@rule("model3d.triangle-soup", recognition="model3d-triangle-soup", severity=4)
def r_soup(doc: ModelDoc):
    """Faces that share no vertices: duplicated, unwelded triangle soup."""
    mesh = doc.mesh
    if len(mesh.faces) < SOUP_MIN_FACES:
        return
    if mesh.source_format != "obj" and mesh.has_normals:
        return  # glTF splits vertices for flat shading; that is not soup
    uses = {}
    for f in mesh.faces:
        for v in f:
            uses[v] = uses.get(v, 0) + 1
    isolated = sum(1 for f in mesh.faces if all(uses[v] == 1 for v in f))
    used = len(uses)
    duplicate = 1.0 - len({doc.remap[v] for v in uses}) / max(1, used)
    ratio = isolated / len(mesh.faces)
    if ratio >= SOUP_ISOLATED_MIN and duplicate >= SOUP_DUPLICATE_MIN:
        yield hit("whole mesh", f"{isolated}/{len(mesh.faces)} faces share no vertex; welding "
                  f"would remove {100 * duplicate:.0f}% of vertices", 0.9)


@rule("model3d.uniform-bevel", recognition="model3d-uniform-bevel-width", severity=3)
def r_bevel(doc: ModelDoc):
    """Every edge chamfered with the same width."""
    widths = bevel_strips(doc)
    if len(widths) < BEVEL_MIN_STRIPS:
        return
    m, s = _mean_std(widths)
    cv = s / m if m else 0.0
    if cv <= BEVEL_MAX_CV:
        yield hit(f"{len(widths)} bevel strips", f"bevel width {m:.4g} on every strip "
                  f"(variation {100 * cv:.1f}%)", 0.85)


@rule("model3d.perfect-symmetry", recognition="model3d-perfect-symmetry", severity=3)
def r_symmetry(doc: ModelDoc):
    """Exact mirror symmetry on an organic or worn object."""
    if len(doc.verts) < SYM_MIN_VERTS:
        return
    organic, why = is_organic(doc)
    if not organic:
        return
    ratio, axis = symmetry(doc)
    if ratio >= SYM_MATCH_MIN:
        yield hit(f"mirror plane across {axis}", f"{100 * ratio:.1f}% of vertices mirror exactly; "
                  f"object reads as organic ({why})", 0.75)


@rule("model3d.over-subdivision", recognition="model3d-uniform-over-subdivision", severity=3)
def r_oversub(doc: ModelDoc):
    """Dense uniform faces that add no silhouette: most neighbors are coplanar."""
    if len(doc.faces) < OVERSUB_MIN_FACES:
        return
    dih = interior_dihedrals(doc)
    if not dih:
        return
    coplanar = sum(1 for d in dih if d < COPLANAR_DEG) / len(dih)
    m, s = _mean_std(doc.areas)
    cv = s / m if m else 0.0
    if coplanar >= OVERSUB_COPLANAR_MIN and cv <= OVERSUB_AREA_CV_MAX:
        yield hit("whole mesh", f"{len(doc.faces)} faces, {100 * coplanar:.0f}% of interior edges "
                  f"coplanar, face size variation {100 * cv:.0f}%", 0.85)


@rule("model3d.disconnected-parts", recognition="model3d-floating-parts", severity=3)
def r_floating(doc: ModelDoc):
    """Disconnected parts floating off the main body."""
    groups = {}
    for fi, c in enumerate(doc.comp):
        groups.setdefault(c, []).append(fi)
    if len(groups) < 2:
        return
    ordered = sorted(groups.values(), key=len, reverse=True)
    main_v = sorted({v for fi in ordered[0] for v in doc.faces[fi]})
    step = max(1, len(main_v) // GAP_SAMPLE)
    main_pts = [doc.verts[v] for v in main_v[::step]]
    floating = 0
    for part in ordered[1:]:
        pv = sorted({v for fi in part for v in doc.faces[fi]})
        pstep = max(1, len(pv) // GAP_SAMPLE)
        gap = min(math.dist(doc.verts[v], q) for v in pv[::pstep] for q in main_pts)
        if gap > FLOAT_GAP_REL * doc.diag:
            floating += 1
            if floating <= 5:
                yield hit(f"part of {len(part)} faces", f"floats {gap:.3g} units from the main "
                          f"body ({100 * gap / doc.diag:.1f}% of size)", 0.85)


@rule("model3d.melted-topology", recognition="model3d-melted-topology", severity=3)
def r_melted(doc: ModelDoc):
    """Dense triangle-only mesh with no sharp edges and irregular topology."""
    if len(doc.faces) < MELT_MIN_FACES or any(len(f) != 3 for f in doc.faces):
        return
    dih = interior_dihedrals(doc)
    if not dih:
        return
    sharp = sum(1 for d in dih if d > SHARP_DEG) / len(dih)
    if sharp > MELT_SHARP_MAX:
        return
    vstd = valence_std(doc)
    slivers = sum(1 for f in doc.faces if _tri_min_angle(*(doc.verts[i] for i in f)) <
                  SLIVER_DEG) / len(doc.faces)
    if vstd >= MELT_VALENCE_STD_MIN or slivers >= MELT_SLIVER_MIN:
        yield hit("whole mesh", f"{len(doc.faces)} triangles, {100 * sharp:.1f}% sharp edges, "
                  f"valence std {vstd:.2f}, {100 * slivers:.0f}% slivers", 0.75)


@rule("model3d.default-material", recognition="model3d-default-material-only", severity=3)
def r_default_material(doc: ModelDoc):
    """No material slots, or only a default-named material."""
    if len(doc.faces) < DEFAULT_MAT_MIN_FACES:
        return
    names = {doc.mesh.face_material[i] if i < len(doc.mesh.face_material) else None
             for i in doc.face_src}
    if all(n is None or DEFAULT_MATERIAL_RE.match(n.strip()) for n in names):
        shown = ", ".join(sorted(repr(n) if n else "none" for n in names))
        yield hit("materials", f"{len(doc.faces)} faces use only: {shown}", 0.85)


def _uv_faces(mesh):
    for fi, f in enumerate(mesh.faces):
        uv = mesh.face_uvs[fi] if fi < len(mesh.face_uvs) else None
        if uv:
            yield fi, f, uv


@rule("model3d.uv-stretch", recognition="model3d-uv-stretch", severity=3)
def r_uv_stretch(doc: ModelDoc):
    """UV area out of proportion to surface area across many faces."""
    mesh = doc.mesh
    ratios, a3_total, auv_total, degenerate = [], 0.0, 0.0, 0
    for _fi, f, uv in _uv_faces(mesh):
        for i in range(1, len(f) - 1):
            p = [mesh.positions[f[0]], mesh.positions[f[i]], mesh.positions[f[i + 1]]]
            t = [mesh.uvs[uv[0]], mesh.uvs[uv[i]], mesh.uvs[uv[i + 1]]]
            a3 = norm(cross(sub(p[1], p[0]), sub(p[2], p[0]))) / 2
            auv = abs((t[1][0] - t[0][0]) * (t[2][1] - t[0][1]) -
                      (t[2][0] - t[0][0]) * (t[1][1] - t[0][1])) / 2
            if a3 <= 1e-12:
                continue
            if auv <= 1e-12:
                degenerate += 1
                continue
            ratios.append(auv / a3)
            a3_total += a3
            auv_total += auv
    total = len(ratios) + degenerate
    if total < UV_MIN_FACES or not ratios:
        return
    k = auv_total / a3_total
    logs = [math.log2(r / k) for r in ratios]
    _, std = _mean_std(logs)
    outliers = (sum(1 for l in logs if abs(l) > UV_OUTLIER_LOG2) + degenerate) / total
    if std >= UV_LOG_STD_MAX or outliers >= UV_OUTLIER_FRAC:
        yield hit("UV layout", f"texel density spread {std:.2f} (log2 std), {100 * outliers:.0f}% "
                  "of triangles stretched 4x or collapsed", 0.8)


@rule("model3d.uv-shattered", recognition="model3d-uv-shattered-islands", severity=3)
def r_uv_shattered(doc: ModelDoc):
    """Auto-unwrap that cut the surface into near per-face UV islands."""
    mesh = doc.mesh
    faces = list(_uv_faces(mesh))
    if len(faces) < UV_ISLAND_MIN_FACES:
        return
    parent = list(range(len(faces)))
    edge_owner = {}
    q = 1e-5
    for idx, (_fi, f, uv) in enumerate(faces):
        corners = [(doc.remap[v], round(mesh.uvs[t][0] / q), round(mesh.uvs[t][1] / q))
                   for v, t in zip(f, uv)]
        for i in range(len(corners)):
            key = frozenset((corners[i], corners[(i + 1) % len(corners)]))
            if key in edge_owner:
                _union(parent, idx, edge_owner[key])
            else:
                edge_owner[key] = idx
    islands = len({_find(parent, i) for i in range(len(faces))})
    ratio = islands / len(faces)
    if ratio >= UV_ISLAND_RATIO_MAX:
        yield hit("UV layout", f"{islands} UV islands for {len(faces)} faces "
                  f"({ratio:.2f} islands per face)", 0.8)
