"""Regenerate the binary and dense test fixtures (standard library only).

Writes deterministic PNG textures to fixtures/texture/{slop,clean}/ and
generated meshes (OBJ text and glTF JSON with embedded buffers) to
fixtures/model3d/{slop,clean}/. Small hand-written OBJ fixtures in the same
folders are left untouched. run_tests.py calls main() before the suite, so the
committed files can always be rebuilt from this script.

    python tests/make_fixtures.py
"""

from __future__ import annotations

import base64
import json
import math
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from scanners.png_reader import encode_png  # noqa: E402

FIX = HERE / "fixtures"
TEX_SIZE = 64
# When True (run_tests.py), existing files are kept: zlib builds differ in
# compressed bytes, and rewriting identical pixels would only add git noise.
SKIP_EXISTING = False


def _keep(path: Path) -> bool:
    return SKIP_EXISTING and path.exists()


# --------------------------------------------------------------------------
# Texture helpers
# --------------------------------------------------------------------------

def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def value_noise(seed: int, size: int, cells: int, wrap: bool = True):
    rnd = random.Random(seed)
    lat = [[rnd.random() for _ in range(cells + 1)] for _ in range(cells + 1)]
    if wrap:
        for row in lat:
            row[cells] = row[0]
        lat[cells] = list(lat[0])
    grid = []
    for y in range(size):
        fy = y / size * cells
        iy, ty = int(fy), _smooth(fy - int(fy))
        row = []
        for x in range(size):
            fx = x / size * cells
            ix, tx = int(fx), _smooth(fx - int(fx))
            a = lat[iy][ix] * (1 - tx) + lat[iy][ix + 1] * tx
            b = lat[iy + 1][ix] * (1 - tx) + lat[iy + 1][ix + 1] * tx
            row.append(a * (1 - ty) + b * ty)
        grid.append(row)
    return grid


def fbm(seed: int, size: int, wrap: bool = True):
    octaves = ((4, 0.50), (8, 0.28), (16, 0.15), (32, 0.07))
    total = sum(a for _, a in octaves)
    out = [[0.0] * size for _ in range(size)]
    for k, (cells, amp) in enumerate(octaves):
        layer = value_noise(seed * 31 + k, size, cells, wrap)
        for y in range(size):
            for x in range(size):
                out[y][x] += amp * layer[y][x] / total
    lo = min(min(r) for r in out)
    hi = max(max(r) for r in out)
    return [[(v - lo) / (hi - lo) for v in row] for row in out]


def worn_luminance(seed: int, size: int = TEX_SIZE):
    """Tileable multi-scale base with wear concentrated in masked regions."""
    base = fbm(seed, size)
    mask = value_noise(seed * 7 + 3, size, 4)
    rnd = random.Random(seed * 13 + 5)
    lum = []
    for y in range(size):
        row = []
        for x in range(size):
            wear = rnd.uniform(-1, 1) * (34 if mask[y][x] > 0.58 else 3)
            row.append(70 + 120 * base[y][x] + wear)
        lum.append(row)
    return lum


def to_rgb(lum, tint=(1.0, 0.86, 0.72)):
    data = bytearray()
    for row in lum:
        for v in row:
            for t in tint:
                data.append(max(0, min(255, int(round(v * t)))))
    return data


def write_png(path: Path, size: int, data, channels: int = 3) -> None:
    if _keep(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(size, size, channels, bytes(data), filter_cycle=True))


def make_textures() -> list:
    n = TEX_SIZE
    slop, clean = FIX / "texture" / "slop", FIX / "texture" / "clean"
    written = []

    def put(path, data, channels=3):
        write_png(path, n, data, channels)
        written.append(path)

    # Slop: non-wrapping noise, so the wrap edges do not match.
    seamless = fbm(2, n, wrap=False)
    put(slop / "texture-visible-tiling-seam.png",
        to_rgb([[60 + 140 * v for v in row] for row in seamless]))
    # Slop: a 16 px patch stamped 4x4.
    rnd = random.Random(4)
    patch = [[rnd.uniform(40, 210) for _ in range(16)] for _ in range(16)]
    put(slop / "texture-short-repeat-period.png",
        to_rgb([[patch[y % 16][x % 16] for x in range(n)] for y in range(n)]))
    # Slop: left half mirrored onto the right half.
    half = worn_luminance(9, n)
    put(slop / "texture-mirror-symmetry.png",
        to_rgb([row[: n // 2] + row[: n // 2][::-1] for row in half]))
    # Slop: a light from the right painted into the albedo.
    lit = worn_luminance(6, n)
    put(slop / "texture-baked-lighting-albedo.png",
        to_rgb([[v * (0.45 + 0.9 * x / (n - 1)) for x, v in enumerate(row)] for row in lit]))
    # Slop: saturated green per-pixel static.
    rnd = random.Random(7)
    noise = bytearray()
    for _ in range(n * n):
        v = rnd.uniform(0.35, 0.85) * 255
        noise.extend((int(v * 0.2), int(v), int(v * 0.15)))
    put(slop / "texture-oversaturated-uniform-noise.png", noise)
    # Slop: a roughness map with one value.
    rnd = random.Random(11)
    put(slop / "texture-flat-roughness.png",
        bytearray(128 + rnd.choice((-1, 0, 0, 1)) for _ in range(n * n)), channels=1)
    # Slop: contrast pushed until blacks and whites clip.
    base = worn_luminance(12, n)
    put(slop / "texture-histogram-clipping.png",
        to_rgb([[(v - 128) * 3.2 + 128 for v in row] for row in base], tint=(1, 1, 1)))
    # Slop: the same busy grain in every region.
    rnd = random.Random(13)
    put(slop / "texture-uniform-detail-density.png",
        to_rgb([[rnd.uniform(70, 190) for _ in range(n)] for _ in range(n)],
               tint=(1.0, 0.97, 0.93)))

    tints = {
        "texture-visible-tiling-seam": (1.0, 0.86, 0.72),
        "texture-short-repeat-period": (0.92, 0.9, 0.86),
        "texture-mirror-symmetry": (1.0, 0.9, 0.8),
        "texture-baked-lighting-albedo": (0.95, 0.88, 0.8),
        "texture-oversaturated-uniform-noise": (0.86, 0.9, 0.84),
        "texture-histogram-clipping": (1.0, 0.93, 0.85),
        "texture-uniform-detail-density": (0.9, 0.85, 0.8),
    }
    for i, (name, tint) in enumerate(sorted(tints.items())):
        put(clean / f"{name}.png", to_rgb(worn_luminance(101 + i, n), tint))
    rough = worn_luminance(120, n)
    put(clean / "texture-flat-roughness.png",
        bytearray(max(0, min(255, int(v))) for row in rough for v in row), channels=1)
    return written


# --------------------------------------------------------------------------
# Mesh helpers
# --------------------------------------------------------------------------

def _newell(pts):
    nx = ny = nz = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    return nx, ny, nz


def orient_outward(verts, faces, center=None):
    """Flip faces whose normal points toward the center (star-shaped meshes)."""
    if center is None:
        center = tuple(sum(v[k] for v in verts) / len(verts) for k in range(3))
    out = []
    for f in faces:
        pts = [verts[i] for i in f]
        n = _newell(pts)
        c = tuple(sum(p[k] for p in pts) / len(pts) - center[k] for k in range(3))
        out.append(f if n[0] * c[0] + n[1] * c[1] + n[2] * c[2] >= 0 else f[::-1])
    return out


class Builder:
    def __init__(self):
        self.verts, self.index = [], {}

    def v(self, p) -> int:
        key = tuple(round(c, 9) for c in p)
        if key not in self.index:
            self.index[key] = len(self.verts)
            self.verts.append(key)
        return self.index[key]


def write_obj(path: Path, name: str, verts, faces, materials, uvs=None, face_uvs=None):
    if _keep(path):
        return
    lines = ["# generated by tests/make_fixtures.py", f"o {name}"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in verts]
    for u, v in uvs or []:
        lines.append(f"vt {u:.6f} {v:.6f}")
    current = None
    for i, f in enumerate(faces):
        mat = materials[i] if isinstance(materials, list) else materials
        if mat and mat != current:
            lines.append(f"usemtl {mat}")
            current = mat
        if face_uvs:
            lines.append("f " + " ".join(f"{a + 1}/{t + 1}" for a, t in zip(f, face_uvs[i])))
        else:
            lines.append("f " + " ".join(str(a + 1) for a in f))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def chamfer_box(widths):
    """Box [-1,1]^3 with every edge chamfered. widths(axis, s1, s2) -> width."""
    b = Builder()
    faces, mats = [], []
    signs = (-1, 1)

    def px(sx, sy, sz):
        return b.v((sx, sy * (1 - widths("z", sx, sy)), sz * (1 - widths("y", sx, sz))))

    def py(sx, sy, sz):
        return b.v((sx * (1 - widths("z", sx, sy)), sy, sz * (1 - widths("x", sy, sz))))

    def pz(sx, sy, sz):
        return b.v((sx * (1 - widths("y", sx, sz)), sy * (1 - widths("x", sy, sz)), sz))

    cyc = ((-1, -1), (1, -1), (1, 1), (-1, 1))
    for s in signs:
        faces.append([px(s, a, c) for a, c in cyc])
        faces.append([py(a, s, c) for a, c in cyc])
        faces.append([pz(a, c, s) for a, c in cyc])
        mats += ["painted_steel"] * 3
    for s1 in signs:
        for s2 in signs:
            faces.append([px(s1, s2, 1), px(s1, s2, -1), py(s1, s2, -1), py(s1, s2, 1)])
            faces.append([px(s1, 1, s2), px(s1, -1, s2), pz(s1, -1, s2), pz(s1, 1, s2)])
            faces.append([py(1, s1, s2), py(-1, s1, s2), pz(-1, s1, s2), pz(1, s1, s2)])
            mats += ["edge_wear"] * 3
    for sx in signs:
        for sy in signs:
            for sz in signs:
                faces.append([px(sx, sy, sz), py(sx, sy, sz), pz(sx, sy, sz)])
                mats.append("edge_wear")
    return b.verts, orient_outward(b.verts, faces, (0, 0, 0)), mats


def icosphere(level: int):
    t = (1 + 5 ** 0.5) / 2
    base = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t),
            (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    verts = [tuple(c / math.sqrt(sum(k * k for k in p)) for c in p) for p in base]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    for _ in range(level):
        cache, nf = {}, []

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                p = [(verts[a][k] + verts[b][k]) / 2 for k in range(3)]
                ln = math.sqrt(sum(c * c for c in p))
                verts.append(tuple(c / ln for c in p))
                cache[key] = len(verts) - 1
            return cache[key]

        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = nf
    return verts, [list(f) for f in faces]


def rock(symmetric: bool):
    verts, faces = icosphere(1)
    out = []
    for x, y, z in verts:
        ax = abs(x) if symmetric else x
        d = 1 + 0.22 * math.sin(3.1 * ax + 1.3) * math.cos(2.3 * y) + 0.14 * math.sin(4.7 * z + 0.4)
        if not symmetric:
            d += 0.18 * math.sin(5.3 * x + 0.7 * y + 0.2) + 0.1 * math.cos(6.1 * x * z)
        out.append((x * d, y * d * 0.8, z * d))
    return out, orient_outward(out, faces, (0, 0, 0))


def subdivided_box(n: int):
    b = Builder()
    faces = []
    for axis in range(3):
        for s in (-1, 1):
            for i in range(n):
                for j in range(n):
                    quad = []
                    for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        u = -1 + 2 * (i + di) / n
                        w = -1 + 2 * (j + dj) / n
                        p = [0.0, 0.0, 0.0]
                        p[axis] = s
                        p[(axis + 1) % 3] = u
                        p[(axis + 2) % 3] = w
                        quad.append(b.v(tuple(p)))
                    faces.append(quad)
    return b.verts, orient_outward(b.verts, faces, (0, 0, 0))


def cylinder(segments: int, height: float):
    verts = []
    for k in (0, 1):
        for i in range(segments):
            a = 2 * math.pi * i / segments
            verts.append((math.cos(a), math.sin(a), height * k - height / 2))
    faces = [[i, (i + 1) % segments, segments + (i + 1) % segments, segments + i]
             for i in range(segments)]
    faces.append(list(range(segments))[::-1])
    faces.append(list(range(segments, 2 * segments)))
    return verts, orient_outward(verts, faces, (0, 0, 0))


def blob(rings: int = 16, segs: int = 24, seed: int = 21):
    rnd = random.Random(seed)
    verts = [(0.0, 0.0, 1.0)]
    for r in range(1, rings):
        th = math.pi * r / rings
        for s in range(segs):
            ph = 2 * math.pi * s / segs
            fade = math.sin(th) ** 2   # no displacement at the poles, so the caps stay smooth
            d = 1 + fade * (0.12 * math.sin(3 * th) * math.cos(2 * ph) +
                            0.06 * math.sin(5 * ph + th))
            verts.append((d * math.sin(th) * math.cos(ph), d * math.sin(th) * math.sin(ph),
                          d * math.cos(th)))
    verts.append((0.0, 0.0, -1.0))
    south = len(verts) - 1

    def ring(r, s):
        return 1 + (r - 1) * segs + (s % segs)

    faces = []
    for s in range(segs):
        faces.append([0, ring(1, s), ring(1, s + 1)])
        faces.append([south, ring(rings - 1, s + 1), ring(rings - 1, s)])
    for r in range(1, rings - 1):
        for s in range(segs):
            a, b, c, d = ring(r, s), ring(r, s + 1), ring(r + 1, s + 1), ring(r + 1, s)
            if rnd.random() < 0.5:
                faces += [[a, b, c], [a, c, d]]
            else:
                faces += [[a, b, d], [b, c, d]]
    return verts, orient_outward(verts, faces, (0, 0, 0))


def grid(n: int):
    verts = [(x / n * 4 - 2, y / n * 4 - 2, 0.0) for y in range(n + 1) for x in range(n + 1)]
    quads = []
    for y in range(n):
        for x in range(n):
            a = y * (n + 1) + x
            quads.append([a, a + 1, a + n + 2, a + n + 1])
    return verts, quads


def gltf_json(positions, triangles, uvs=None, material=None):
    pos_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
    idx = [i for t in triangles for i in t]
    idx_bytes = b"".join(struct.pack("<H", i) for i in idx)
    idx_bytes += b"\x00" * ((4 - len(idx_bytes) % 4) % 4)
    uv_bytes = b"".join(struct.pack("<2f", *t) for t in uvs) if uvs else b""
    blob_ = pos_bytes + idx_bytes + uv_bytes
    xs, ys, zs = zip(*positions)
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes)},
        {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(idx) * 2},
    ]
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3",
         "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
        {"bufferView": 1, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
    ]
    attributes = {"POSITION": 0}
    if uvs:
        views.append({"buffer": 0, "byteOffset": len(pos_bytes) + len(idx_bytes),
                      "byteLength": len(uv_bytes)})
        accessors.append({"bufferView": 2, "componentType": 5126, "count": len(uvs),
                          "type": "VEC2"})
        attributes["TEXCOORD_0"] = 2
    prim = {"attributes": attributes, "indices": 1, "mode": 4}
    doc = {
        "asset": {"version": "2.0", "generator": "mandragora tests/make_fixtures.py"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "panel"}],
        "meshes": [{"name": "panel", "primitives": [prim]}],
        "buffers": [{"byteLength": len(blob_),
                     "uri": "data:application/octet-stream;base64," +
                            base64.b64encode(blob_).decode("ascii")}],
        "bufferViews": views,
        "accessors": accessors,
    }
    if material:
        doc["materials"] = [{"name": material}]
        prim["material"] = 0
    return doc


def write_json(path: Path, doc) -> None:
    if _keep(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write(json.dumps(doc, indent=1) + "\n")


def _tris(quads):
    return [t for q in quads for t in ([q[0], q[1], q[2]], [q[0], q[2], q[3]])]


CUBE_V = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
          (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
CUBE_Q = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [3, 7, 6, 2], [0, 4, 7, 3], [1, 2, 6, 5]]


def make_meshes() -> list:
    slop, clean = FIX / "model3d" / "slop", FIX / "model3d" / "clean"
    written = []

    def obj(path, *args, **kw):
        write_obj(path, *args, **kw)
        written.append(path)

    v, f, m = chamfer_box(lambda axis, a, b: 0.1)
    obj(slop / "model3d-uniform-bevel-width.obj", "crate", v, f, m)

    def varied(axis, a, b):
        if axis == "z":
            return 0.04                          # vertical edges, protected
        top = b > 0 if axis in ("x", "y") else False
        return 0.15 if top else 0.08             # top edges worn, base edges medium

    v, f, m = chamfer_box(varied)
    obj(clean / "model3d-uniform-bevel-width.obj", "crate", v, f, m)

    v, f = rock(symmetric=True)
    obj(slop / "model3d-perfect-symmetry.obj", "rock_boulder", v, f, "granite")
    v, f = rock(symmetric=False)
    obj(clean / "model3d-perfect-symmetry.obj", "rock_boulder", v, f, "granite")

    v, f = subdivided_box(6)
    obj(slop / "model3d-uniform-over-subdivision.obj", "crate", v, f, "plywood")
    v, f = cylinder(24, 1.2)
    obj(clean / "model3d-uniform-over-subdivision.obj", "drum", v, f, "painted_steel")

    v, f = blob()
    obj(slop / "model3d-melted-topology.obj", "scan_result", v, f, "clay")
    verts, faces = icosphere(1)
    rnd = random.Random(31)
    faceted = [tuple(c * rnd.uniform(0.75, 1.25) for c in p) for p in verts]
    obj(clean / "model3d-melted-topology.obj", "rock_faceted", faceted,
        orient_outward(faceted, faces, (0, 0, 0)), "basalt")

    v, quads = grid(6)
    uvs, fuv = [], []
    for k, q in enumerate(quads):
        base = len(uvs)
        ox, oy = (k % 6) * 0.16, (k // 6) * 0.16
        uvs += [(ox, oy), (ox + 0.12, oy), (ox + 0.12, oy + 0.12), (ox, oy + 0.12)]
        fuv.append([base, base + 1, base + 2, base + 3])
    obj(slop / "model3d-uv-shattered-islands.obj", "floor_panel", v, quads, "tiles",
        uvs=uvs, face_uvs=fuv)
    shared = [((x + 2) / 4, (y + 2) / 4) for x, y, _z in v]
    obj(clean / "model3d-uv-shattered-islands.obj", "floor_panel", v, quads, "tiles",
        uvs=shared, face_uvs=[list(q) for q in quads])

    v, quads = grid(4)
    tris = _tris(quads)
    squashed = [((x + 2) * 0.25 if x < 0.5 else 0.625 + (x - 0.5) * 0.02, (y + 2) / 4)
                for x, y, _z in v]
    write_json(slop / "model3d-uv-stretch.gltf", gltf_json(v, tris, squashed, "plaster"))
    even = [((x + 2) / 4, (y + 2) / 4) for x, y, _z in v]
    write_json(clean / "model3d-uv-stretch.gltf", gltf_json(v, tris, even, "plaster"))
    written += [slop / "model3d-uv-stretch.gltf", clean / "model3d-uv-stretch.gltf"]

    write_json(slop / "model3d-default-material-only.gltf", gltf_json(CUBE_V, _tris(CUBE_Q)))
    written.append(slop / "model3d-default-material-only.gltf")
    return written


def main(skip_existing: bool = False) -> int:
    global SKIP_EXISTING
    SKIP_EXISTING = skip_existing
    files = make_textures() + make_meshes()
    verb = "checked" if skip_existing else "wrote"
    print(f"make_fixtures: {verb} {len(files)} generated fixture files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
