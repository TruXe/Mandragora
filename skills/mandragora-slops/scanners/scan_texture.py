"""Texture domain: 2D textures and material maps (PNG input).

The loader decodes the PNG with png_reader, box-downsamples it to an analysis
grid and computes luminance and saturation. Map type comes from file name
tokens (albedo, roughness, normal, metallic, ao, height, mask) and decides
which rules apply: lighting and saturation checks only make sense on albedo.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from scanners.core import ScanError, hit, read_bytes, register_domain, rule
from scanners.png_reader import PngError, decode_png

DOMAIN = "texture"
EXTENSIONS = (".png",)
UNSUPPORTED_IMAGES = (".jpg", ".jpeg", ".webp", ".tga", ".bmp", ".exr", ".tif", ".tiff", ".psd")

# ---------------------------------------------------------------- thresholds
# Analysis grid side. 128 keeps autocorrelation under a second in pure Python
# and still resolves repeats down to 4 px tiles on a 512 px texture.
ANALYSIS_SIDE = 128
# Wrap seam: mean |last - first| column/row difference over the mean interior
# neighbor difference. Tileable textures sit near 1.0; 2.0 is a visible seam.
SEAM_RATIO_MAX = 2.0
# Below this absolute difference (0..255) a seam is invisible on screen.
SEAM_MIN_LEVELS = 8.0
# Columns (rows) on each side of the wrap edge used as the local reference.
SEAM_REFERENCE_BAND = 4
# Repeat period: correlation at a lag must reach this, after dipping by at
# least PERIOD_DIP at a shorter lag (smooth images correlate at small lags).
PERIOD_CORR_MIN = 0.80
PERIOD_DIP = 0.30
PERIOD_MIN_LAG = 3
# Mirror symmetry: correlation between the image and its flipped copy.
MIRROR_CORR_MIN = 0.90
# Baked lighting: block-mean plane or radial fit across the texture. A change
# of 40 levels with R^2 >= 0.6 is a light direction or vignette, not material.
LIGHT_BLOCKS = 8
LIGHT_MIN_RANGE = 40.0
LIGHT_MIN_R2 = 0.60
# Oversaturated uniform noise: high mean saturation, low spread, and detail at
# a single scale (coarse/fine energy ratio; white noise gives about 0.25).
SAT_MEAN_MIN = 0.55
SAT_STD_MAX = 0.12
SCALE_RATIO_MAX = 0.35
SCALE_BLOCK = 4
# Flat roughness: a roughness/gloss map with this little variation (0..255)
# renders as uniform plastic.
ROUGHNESS_STD_MAX = 6.0
# Histogram clipping: share of sampled pixels at 0..2 or 253..255.
CLIP_LEVEL_LOW, CLIP_LEVEL_HIGH = 2, 253
CLIP_FRACTION_MAX = 0.03
CLIP_SAMPLE_MAX = 65536
# Detail density: coefficient of variation of per-block gradient energy.
# Real wear concentrates detail; below 0.12 every block is equally busy.
DETAIL_BLOCKS = 8
DETAIL_CV_MAX = 0.12
DETAIL_MIN_ENERGY = 3.0

MAP_TOKENS = {
    "normal": {"normal", "nrm", "nor", "normalmap", "normalgl", "normaldx"},
    "roughness": {"roughness", "rough", "rgh", "gloss", "glossiness", "specular", "spec"},
    "metallic": {"metallic", "metalness", "metal", "mtl"},
    "ao": {"ao", "occlusion", "ambientocclusion"},
    "height": {"height", "disp", "displacement", "bump"},
    "mask": {"mask", "opacity", "alpha"},
}


@dataclass
class TextureDoc:
    path: Path
    width: int
    height: int
    map_type: str
    lum: list            # analysis grid rows of luminance floats 0..255
    sat: list            # analysis grid rows of HSV saturation 0..1
    clip_low: float
    clip_high: float

    @property
    def gw(self):
        return len(self.lum[0])

    @property
    def gh(self):
        return len(self.lum)


def map_type_of(path: Path) -> str:
    tokens = set(re.split(r"[^a-z0-9]+", path.stem.lower()))
    for kind, names in MAP_TOKENS.items():
        if tokens & names:
            return kind
    return "albedo"


def _luma(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def build_doc(image, path: Path) -> TextureDoc:
    w, h = image.width, image.height
    fx = max(1, math.ceil(w / ANALYSIS_SIDE))
    fy = max(1, math.ceil(h / ANALYSIS_SIDE))
    gw, gh = w // fx, h // fy
    if gw < 4 or gh < 4:
        raise ScanError(f"{path.name}: {w}x{h} is too small to analyse")
    acc_l = [[0.0] * gw for _ in range(gh)]
    acc_s = [[0.0] * gw for _ in range(gh)]
    step = max(1, (w * h) // CLIP_SAMPLE_MAX)
    low = high = sampled = 0
    idx = 0
    for y, row in enumerate(image.rgb_rows()):
        gy = y // fy
        for x, (r, g, b) in enumerate(row):
            lv = _luma(r, g, b)
            if idx % step == 0:
                sampled += 1
                if lv <= CLIP_LEVEL_LOW:
                    low += 1
                elif lv >= CLIP_LEVEL_HIGH:
                    high += 1
            idx += 1
            if gy >= gh:
                continue
            gx = x // fx
            if gx >= gw:
                continue
            mx = max(r, g, b)
            acc_l[gy][gx] += lv
            acc_s[gy][gx] += (mx - min(r, g, b)) / mx if mx else 0.0
    n = fx * fy
    lum = [[v / n for v in row] for row in acc_l]
    sat = [[v / n for v in row] for row in acc_s]
    return TextureDoc(path, w, h, map_type_of(path), lum, sat,
                      low / max(1, sampled), high / max(1, sampled))


def load(path: Path) -> TextureDoc:
    if path.suffix.lower() in UNSUPPORTED_IMAGES:
        raise ScanError(f"{path.name}: only PNG is decoded (stdlib only); convert it to PNG first")
    try:
        image = decode_png(read_bytes(path))
    except PngError as exc:
        raise ScanError(f"{path.name}: {exc}") from exc
    return build_doc(image, path)


def sniff(path: Path, head: bytes) -> int:
    ext = path.suffix.lower()
    if ext == ".png":
        return 90 if head.startswith(b"\x89PNG") else 10
    if ext in UNSUPPORTED_IMAGES:
        return 40
    return 0


register_domain(DOMAIN, load=load, sniff=sniff, extensions=EXTENSIONS + UNSUPPORTED_IMAGES,
                description="2D textures and material maps (PNG)")


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def _flat(grid):
    return [v for row in grid for v in row]


def _mean_std(values):
    n = len(values)
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / n
    return m, math.sqrt(var)


def pearson(a, b) -> float:
    ma, sa = _mean_std(a)
    mb, sb = _mean_std(b)
    if sa < 1e-9 or sb < 1e-9:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) * sa * sb)


def seam_ratios(L):
    """Wrap-edge difference against neighbor steps in the bands next to that edge.
    A local reference keeps a worn band along one border from faking a seam."""
    h, w = len(L), len(L[0])
    band = SEAM_REFERENCE_BAND
    xs = [x for x in range(band) if x + 1 < w] + [x for x in range(w - 1 - band, w - 1) if x >= 0]
    ys = [y for y in range(band) if y + 1 < h] + [y for y in range(h - 1 - band, h - 1) if y >= 0]
    seam_x = sum(abs(L[y][w - 1] - L[y][0]) for y in range(h)) / h
    inner_x = sum(abs(L[y][x + 1] - L[y][x]) for y in range(h) for x in xs) / (h * len(xs))
    seam_y = sum(abs(L[h - 1][x] - L[0][x]) for x in range(w)) / w
    inner_y = sum(abs(L[y + 1][x] - L[y][x]) for y in ys for x in range(w)) / (len(ys) * w)
    return (seam_x, seam_x / (inner_x + 1e-6)), (seam_y, seam_y / (inner_y + 1e-6))


def autocorr(L, axis: str) -> dict:
    """Wrap-around autocorrelation for lags 1..n/2 along one axis."""
    h, w = len(L), len(L[0])
    m = sum(_flat(L)) / (w * h)
    d = [[v - m for v in row] for row in L]
    denom = sum(v * v for row in d for v in row)
    if denom < 1e-9:
        return {}
    out = {}
    n = w if axis == "x" else h
    for lag in range(1, n // 2 + 1):
        if axis == "x":
            s = sum(row[x] * row[(x + lag) % w] for row in d for x in range(w))
        else:
            s = sum(d[y][x] * d[(y + lag) % h][x] for y in range(h) for x in range(w))
        out[lag] = s / denom
    return out


def repeat_period(L):
    best = None
    for axis in ("x", "y"):
        c = autocorr(L, axis)
        lags = sorted(c)
        for lag in lags:
            if lag < PERIOD_MIN_LAG or c[lag] < PERIOD_CORR_MIN:
                continue
            dip = min(c[l] for l in lags if l < lag)
            if dip <= c[lag] - PERIOD_DIP:
                if best is None or c[lag] > best[2]:
                    best = (axis, lag, c[lag])
                break
    return best


def mirror_scores(L):
    flat = _flat(L)
    lr = [v for row in L for v in reversed(row)]
    ud = [v for row in reversed(L) for v in row]
    return pearson(flat, lr), pearson(flat, ud)


def block_means(L, blocks: int):
    h, w = len(L), len(L[0])
    bh, bw = max(1, h // blocks), max(1, w // blocks)
    out = []
    for by in range(blocks):
        row = []
        for bx in range(blocks):
            vals = [L[y][x] for y in range(by * bh, min(h, (by + 1) * bh))
                    for x in range(bx * bw, min(w, (bx + 1) * bw))]
            row.append(sum(vals) / len(vals) if vals else 0.0)
        out.append(row)
    return out


def _fit(xs_list, z):
    """Least squares z ~ a + sum(b_i * x_i) for 1 or 2 centered regressors.
    Returns (coefficients, r2)."""
    n = len(z)
    mz = sum(z) / n
    sst = sum((v - mz) ** 2 for v in z)
    if sst < 1e-9:
        return [0.0] * len(xs_list), 0.0
    cols = []
    for xs in xs_list:
        mx = sum(xs) / n
        cols.append([v - mx for v in xs])
    if len(cols) == 1:
        sxx = sum(v * v for v in cols[0])
        b = [sum(x * (y - mz) for x, y in zip(cols[0], z)) / sxx if sxx else 0.0]
    else:
        a11 = sum(v * v for v in cols[0])
        a22 = sum(v * v for v in cols[1])
        a12 = sum(p * q for p, q in zip(cols[0], cols[1]))
        b1 = sum(p * (y - mz) for p, y in zip(cols[0], z))
        b2 = sum(q * (y - mz) for q, y in zip(cols[1], z))
        det = a11 * a22 - a12 * a12
        b = [(b1 * a22 - b2 * a12) / det, (a11 * b2 - a12 * b1) / det] if det else [0.0, 0.0]
    pred = [mz + sum(bi * col[i] for bi, col in zip(b, cols)) for i in range(n)]
    ssr = sum((zi - pi) ** 2 for zi, pi in zip(z, pred))
    return b, 1.0 - ssr / sst


def lighting_fit(L):
    B = block_means(L, LIGHT_BLOCKS)
    n = len(B)
    us, vs, rs, z = [], [], [], []
    for j, row in enumerate(B):
        for i, val in enumerate(row):
            u, v = (i + 0.5) / n, (j + 0.5) / n
            us.append(u)
            vs.append(v)
            rs.append(((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.5)
            z.append(val)
    (bu, bv), r2_plane = _fit([us, vs], z)
    (br,), r2_radial = _fit([rs], z)
    return abs(bu) + abs(bv), r2_plane, br, r2_radial


def scale_ratio(L):
    h, w = len(L), len(L[0])
    fine = sum(abs(L[y][x + 1] - L[y][x]) for y in range(h) for x in range(w - 1)) / (h * (w - 1))
    k = SCALE_BLOCK
    B = block_means(L, max(2, w // k))
    bh, bw = len(B), len(B[0])
    coarse = sum(abs(B[y][x + 1] - B[y][x]) for y in range(bh) for x in range(bw - 1)) / \
        max(1, bh * (bw - 1))
    return coarse / (fine + 1e-6), fine


def detail_cv(L):
    h, w = len(L), len(L[0])
    bh, bw = max(2, h // DETAIL_BLOCKS), max(2, w // DETAIL_BLOCKS)
    energies = []
    for by in range(DETAIL_BLOCKS):
        for bx in range(DETAIL_BLOCKS):
            ys = range(by * bh, min(h, (by + 1) * bh))
            xs = range(bx * bw, min(w - 1, (bx + 1) * bw))
            vals = [abs(L[y][x + 1] - L[y][x]) for y in ys for x in xs]
            if vals:
                energies.append(sum(vals) / len(vals))
    m, s = _mean_std(energies)
    return (s / m if m > 1e-9 else 0.0), m


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

@rule("texture.tiling-seam", recognition="texture-visible-tiling-seam", severity=4)
def r_seam(doc: TextureDoc):
    """Wrap-around edges differ far more than neighboring pixels inside."""
    (sx, rx), (sy, ry) = seam_ratios(doc.lum)
    for axis, seam, ratio in (("vertical (left/right)", sx, rx), ("horizontal (top/bottom)", sy,
                                                                   ry)):
        if ratio >= SEAM_RATIO_MAX and seam >= SEAM_MIN_LEVELS:
            yield hit(f"{axis} wrap edge", f"seam {seam:.1f} levels, {ratio:.1f}x the interior "
                      "neighbor difference", 0.85)


@rule("texture.repeat-period", recognition="texture-short-repeat-period", severity=3)
def r_repeat(doc: TextureDoc):
    """The image repeats itself inside its own bounds at a short period."""
    best = repeat_period(doc.lum)
    if best:
        axis, lag, c = best
        scale = doc.width / doc.gw if axis == "x" else doc.height / doc.gh
        yield hit(f"{axis} axis", f"repeats every {lag * scale:.0f} px (correlation {c:.2f})", 0.85)


@rule("texture.mirror-axis", recognition="texture-mirror-symmetry", severity=3)
def r_mirror(doc: TextureDoc):
    """Detail mirrored across a vertical or horizontal axis."""
    if doc.map_type == "normal":
        return
    lr, ud = mirror_scores(doc.lum)
    for name, c in (("vertical axis (left/right mirror)", lr), ("horizontal axis (top/bottom "
                                                                "mirror)", ud)):
        if c >= MIRROR_CORR_MIN:
            yield hit(name, f"image vs flipped copy correlation {c:.2f}", 0.85)


@rule("texture.baked-lighting", recognition="texture-baked-lighting-albedo", severity=3)
def r_baked_light(doc: TextureDoc):
    """Directional gradient or vignette baked into an albedo map."""
    if doc.map_type != "albedo":
        return
    rng, r2p, radial, r2r = lighting_fit(doc.lum)
    if rng >= LIGHT_MIN_RANGE and r2p >= LIGHT_MIN_R2:
        yield hit("whole image", f"directional light gradient of {rng:.0f} levels (R^2 {r2p:.2f})",
                  0.8)
    elif abs(radial) >= LIGHT_MIN_RANGE and r2r >= LIGHT_MIN_R2:
        kind = "dark edges (vignette or AO)" if radial < 0 else "bright edges"
        yield hit("whole image", f"radial falloff of {abs(radial):.0f} levels, {kind} "
                  f"(R^2 {r2r:.2f})", 0.8)


@rule("texture.uniform-noise", recognition="texture-oversaturated-uniform-noise", severity=3)
def r_uniform_noise(doc: TextureDoc):
    """Oversaturated color with noise at one scale only."""
    if doc.map_type != "albedo":
        return
    m, s = _mean_std(_flat(doc.sat))
    ratio, _fine = scale_ratio(doc.lum)
    if m >= SAT_MEAN_MIN and s <= SAT_STD_MAX and ratio <= SCALE_RATIO_MAX:
        yield hit("whole image", f"saturation mean {m:.2f} std {s:.2f}; coarse/fine detail "
                  f"ratio {ratio:.2f}", 0.8)


@rule("texture.flat-roughness", recognition="texture-flat-roughness", severity=3)
def r_flat_roughness(doc: TextureDoc):
    """Roughness or gloss map with almost no variation."""
    if doc.map_type != "roughness":
        return
    m, s = _mean_std(_flat(doc.lum))
    if s <= ROUGHNESS_STD_MAX:
        yield hit("whole image", f"roughness {m:.0f}/255 with std {s:.1f}: one value everywhere",
                  0.9)


@rule("texture.histogram-clip", recognition="texture-histogram-clipping", severity=3)
def r_clip(doc: TextureDoc):
    """Crushed blacks or blown whites in an albedo map."""
    if doc.map_type != "albedo":
        return
    if doc.clip_low >= CLIP_FRACTION_MAX:
        yield hit("histogram", f"{100 * doc.clip_low:.1f}% of pixels at pure black", 0.85)
    if doc.clip_high >= CLIP_FRACTION_MAX:
        yield hit("histogram", f"{100 * doc.clip_high:.1f}% of pixels at pure white", 0.85)


@rule("texture.detail-density", recognition="texture-uniform-detail-density", severity=3)
def r_detail_density(doc: TextureDoc):
    """Every region of the texture carries the same amount of detail."""
    if doc.map_type not in ("albedo", "roughness", "height"):
        return
    cv, energy = detail_cv(doc.lum)
    if energy >= DETAIL_MIN_ENERGY and cv <= DETAIL_CV_MAX:
        yield hit("whole image", f"detail energy {energy:.1f} varies only {100 * cv:.0f}% "
                  "between regions", 0.75)
