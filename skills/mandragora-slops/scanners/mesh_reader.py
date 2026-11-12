"""Mesh readers: Wavefront OBJ and glTF 2.0 (JSON .gltf or binary .glb).

glTF buffers may be embedded data URIs (base64) or sidecar files next to the
.gltf. Node transforms (matrix or TRS) are applied. Only triangle primitives
are read (mode 4, plus strips and fans converted to triangles).
Standard library only.
"""

from __future__ import annotations

import base64
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path


class MeshError(ValueError):
    pass


@dataclass
class Mesh:
    positions: list = field(default_factory=list)     # (x, y, z)
    faces: list = field(default_factory=list)         # lists of position indices
    face_uvs: list = field(default_factory=list)      # per face: list of uv indices or None
    uvs: list = field(default_factory=list)           # (u, v)
    face_material: list = field(default_factory=list)  # per face: material name or None
    materials: list = field(default_factory=list)     # declared material names
    names: list = field(default_factory=list)         # object, group, node and mesh names
    has_normals: bool = False
    source_format: str = "obj"


# --------------------------------------------------------------------------
# OBJ
# --------------------------------------------------------------------------

def _obj_index(token: str, count: int) -> int:
    i = int(token)
    return i - 1 if i > 0 else count + i


def parse_obj(text: str) -> Mesh:
    mesh = Mesh(source_format="obj")
    material = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        tag = parts[0]
        try:
            if tag == "v":
                mesh.positions.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "vt":
                mesh.uvs.append((float(parts[1]), float(parts[2]) if len(parts) > 2 else 0.0))
            elif tag == "vn":
                mesh.has_normals = True
            elif tag == "f":
                vi, ti = [], []
                for corner in parts[1:]:
                    bits = corner.split("/")
                    vi.append(_obj_index(bits[0], len(mesh.positions)))
                    if len(bits) > 1 and bits[1]:
                        ti.append(_obj_index(bits[1], len(mesh.uvs)))
                if len(vi) < 3:
                    continue
                mesh.faces.append(vi)
                mesh.face_uvs.append(ti if len(ti) == len(vi) else None)
                mesh.face_material.append(material)
            elif tag == "usemtl":
                material = " ".join(parts[1:])
                if material not in mesh.materials:
                    mesh.materials.append(material)
            elif tag in ("o", "g"):
                mesh.names.append(" ".join(parts[1:]))
        except (IndexError, ValueError) as exc:
            raise MeshError(f"OBJ line {lineno}: {raw.strip()[:60]!r} ({exc})") from exc
    n = len(mesh.positions)
    for f in mesh.faces:
        if any(i < 0 or i >= n for i in f):
            raise MeshError("OBJ face references a vertex that does not exist")
    return mesh


# --------------------------------------------------------------------------
# glTF
# --------------------------------------------------------------------------

COMPONENTS = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4),
              5126: ("f", 4)}
TYPE_SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _node_matrix(node: dict):
    if "matrix" in node:
        m = node["matrix"]  # column-major
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    tx, ty, tz = node.get("translation", (0, 0, 0))
    qx, qy, qz, qw = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    rot = [
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ]
    return [[rot[0][0] * sx, rot[0][1] * sy, rot[0][2] * sz, tx],
            [rot[1][0] * sx, rot[1][1] * sy, rot[1][2] * sz, ty],
            [rot[2][0] * sx, rot[2][1] * sy, rot[2][2] * sz, tz],
            [0, 0, 0, 1]]


IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


class _Gltf:
    def __init__(self, doc: dict, base: Path, bin_chunk: bytes | None):
        self.doc, self.base, self.bin_chunk = doc, base, bin_chunk
        self._buffers = {}

    def buffer(self, idx: int) -> bytes:
        if idx in self._buffers:
            return self._buffers[idx]
        info = self.doc["buffers"][idx]
        uri = info.get("uri")
        if uri is None:
            if self.bin_chunk is None:
                raise MeshError("buffer without uri and no GLB binary chunk")
            data = self.bin_chunk
        elif uri.startswith("data:"):
            try:
                data = base64.b64decode(uri.split(",", 1)[1])
            except (IndexError, ValueError) as exc:
                raise MeshError("malformed data URI buffer") from exc
        else:
            target = (self.base / uri).resolve()
            if not target.is_file():
                raise MeshError(f"sidecar buffer {uri!r} not found next to the glTF file")
            data = target.read_bytes()
        self._buffers[idx] = data
        return data

    def accessor(self, idx: int) -> list:
        acc = self.doc["accessors"][idx]
        if "bufferView" not in acc:
            return [(0.0,) * TYPE_SIZE[acc["type"]]] * acc["count"]
        view = self.doc["bufferViews"][acc["bufferView"]]
        data = self.buffer(view["buffer"])
        fmt, size = COMPONENTS[acc["componentType"]]
        n = TYPE_SIZE[acc["type"]]
        stride = view.get("byteStride") or size * n
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        out = []
        for i in range(acc["count"]):
            out.append(struct.unpack_from("<" + fmt * n, data, start + i * stride))
        if acc.get("normalized") and fmt != "f":
            scale = float((1 << (8 * size - (1 if fmt.islower() else 0))) - 1)
            out = [tuple(v / scale for v in t) for t in out]
        return out


def _triangles(indices: list, mode: int) -> list:
    if mode == 4:
        return [indices[i:i + 3] for i in range(0, len(indices) - 2, 3)]
    if mode == 5:
        tris = []
        for i in range(len(indices) - 2):
            a, b, c = indices[i:i + 3]
            tris.append([a, b, c] if i % 2 == 0 else [b, a, c])
        return tris
    if mode == 6:
        return [[indices[0], indices[i], indices[i + 1]] for i in range(1, len(indices) - 1)]
    return []


def parse_gltf_doc(doc: dict, base: Path, bin_chunk: bytes | None, fmt: str) -> Mesh:
    g = _Gltf(doc, base, bin_chunk)
    mesh = Mesh(source_format=fmt)
    materials = doc.get("materials", [])
    mesh.materials = [m.get("name", "") for m in materials]
    nodes = doc.get("nodes", [])

    def emit(mesh_idx: int, matrix):
        m = doc["meshes"][mesh_idx]
        if m.get("name"):
            mesh.names.append(m["name"])
        for prim in m.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            pos = g.accessor(attrs["POSITION"])
            base_index = len(mesh.positions)
            for x, y, z in pos:
                mesh.positions.append(tuple(matrix[r][0] * x + matrix[r][1] * y + matrix[r][2] * z
                                            + matrix[r][3] for r in range(3)))
            uv_base = len(mesh.uvs)
            has_uv = "TEXCOORD_0" in attrs
            if has_uv:
                mesh.uvs.extend((t[0], t[1]) for t in g.accessor(attrs["TEXCOORD_0"]))
            if "NORMAL" in attrs:
                mesh.has_normals = True
            idx = [t[0] for t in g.accessor(prim["indices"])] if "indices" in prim \
                else list(range(len(pos)))
            mat_idx = prim.get("material")
            mat_name = None
            if mat_idx is not None and mat_idx < len(materials):
                mat_name = materials[mat_idx].get("name", "")
            for tri in _triangles(idx, prim.get("mode", 4)):
                mesh.faces.append([base_index + i for i in tri])
                mesh.face_uvs.append([uv_base + i for i in tri] if has_uv else None)
                mesh.face_material.append(mat_name)

    def walk(node_idx: int, parent, depth: int = 0):
        if depth > 64:
            raise MeshError("glTF node hierarchy is too deep or cyclic")
        node = nodes[node_idx]
        if node.get("name"):
            mesh.names.append(node["name"])
        matrix = _mat_mul(parent, _node_matrix(node))
        if "mesh" in node:
            emit(node["mesh"], matrix)
        for child in node.get("children", []):
            walk(child, matrix, depth + 1)

    scenes = doc.get("scenes")
    if scenes:
        scene = scenes[doc.get("scene", 0)]
        for n in scene.get("nodes", []):
            walk(n, IDENTITY)
    elif nodes:
        children = {c for n in nodes for c in n.get("children", [])}
        for i in range(len(nodes)):
            if i not in children:
                walk(i, IDENTITY)
    else:
        for i in range(len(doc.get("meshes", []))):
            emit(i, IDENTITY)
    return mesh


def parse_glb(blob: bytes, base: Path) -> Mesh:
    if len(blob) < 20 or blob[:4] != b"glTF":
        raise MeshError("not a GLB file")
    _magic, version, _length = struct.unpack_from("<4sII", blob, 0)
    if version != 2:
        raise MeshError(f"GLB version {version} is not supported")
    pos, doc, bin_chunk = 12, None, None
    while pos + 8 <= len(blob):
        clen, ctype = struct.unpack_from("<II", blob, pos)
        chunk = blob[pos + 8:pos + 8 + clen]
        if ctype == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_chunk = chunk
        pos += 8 + clen
    if doc is None:
        raise MeshError("GLB without JSON chunk")
    return parse_gltf_doc(doc, base, bin_chunk, "glb")


def read_mesh(path) -> Mesh:
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext == ".obj":
            return parse_obj(path.read_text(encoding="utf-8", errors="replace"))
        if ext == ".gltf":
            return parse_gltf_doc(json.loads(path.read_text(encoding="utf-8")), path.parent, None,
                                  "gltf")
        if ext == ".glb":
            return parse_glb(path.read_bytes(), path.parent)
    except (KeyError, IndexError, TypeError, struct.error, json.JSONDecodeError) as exc:
        raise MeshError(f"{path.name}: malformed {ext[1:]} ({type(exc).__name__}: {exc})") from exc
    raise MeshError(f"{path.name}: unsupported mesh format {ext}")


# --------------------------------------------------------------------------
# Geometry helpers shared by the scanner and the ASCII renderer
# --------------------------------------------------------------------------

def bbox(points):
    xs, ys, zs = zip(*points)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def diagonal(points) -> float:
    lo, hi = bbox(points)
    return math.dist(lo, hi)


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a) -> float:
    return math.sqrt(dot(a, a))


def newell_normal(pts):
    """Unnormalized polygon normal (length = 2 * area) via Newell's method."""
    nx = ny = nz = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    return (nx, ny, nz)
