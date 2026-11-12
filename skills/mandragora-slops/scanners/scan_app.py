"""App domain: desktop and mobile UI code.

Frameworks recognized: XAML/AXAML (WPF, WinUI, Avalonia, MAUI), SwiftUI,
Jetpack Compose, Flutter, QML, Dear ImGui (C++), React Native, and HTML-based
app shells (Electron, Tauri) through the web helpers. Native code is read with
targeted regular expressions; markup reuses scan_web's parsed tree.

The app domain is chosen explicitly with --domain app, or automatically when a
file shows a known UI framework marker (import SwiftUI, @Composable, ImGui::).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from scanners import scan_web as web
from scanners.core import hit, line_of, read_text, register_domain, rule

DOMAIN = "app"
EXTENSIONS = (".xaml", ".axaml", ".swift", ".kt", ".kts", ".qml", ".dart", ".cpp", ".cc", ".cxx",
              ".h", ".hpp", ".hh")

# ---------------------------------------------------------------- thresholds
# Corner radius values needed before "all equal" means something. Three equal
# radii happen in any small view; four or more equal values is a blanket rule.
UNIFORM_RADIUS_MIN_COUNT = 4
# Radii below this (pt/dp/px) read as a subtle softening, not a design rule.
UNIFORM_RADIUS_MIN_VALUE = 8
# Identical tile invocations that make a grid read as a template.
TILE_REPEAT_MIN = 4
# Status dots in native toolkits: 6 to 10 points wide.
DOT_MAX = 10
# A pill outline and its dot must sit within this many lines of each other.
PILL_WINDOW_LINES = 25
# Pill radius: Compose percent 50 or radii at or above this read as capsules.
PILL_RADIUS_MIN = 10
# Glow shadows need at least this blur radius and zero offset.
GLOW_MIN_RADIUS = 8
GLOW_MIN_COUNT = 2
# Translucent white used by glass panels (alpha 0..1).
GLASS_ALPHA_RANGE = (0.04, 0.45)
# Lines searched around a blur/material call for the white fill and white stroke.
GLASS_WINDOW_LINES = 15
# Percent-delta strings needed next to a greeting to form a stat row.
STAT_DELTA_MIN = 3
# Characters searched after a gradient keyword for its color stops.
GRADIENT_WINDOW_CHARS = 600

SWIFT_NAMED = {
    "red": (255, 59, 48), "orange": (255, 149, 0), "yellow": (255, 204, 0),
    "green": (52, 199, 89), "mint": (0, 199, 190), "teal": (48, 176, 199),
    "cyan": (50, 173, 230), "blue": (0, 122, 255), "indigo": (88, 86, 214),
    "purple": (175, 82, 222), "pink": (255, 45, 85), "brown": (162, 132, 94),
    "gray": (142, 142, 147), "white": (255, 255, 255), "black": (0, 0, 0),
}
COMPOSE_NAMED = {
    "Red": (255, 0, 0), "Green": (0, 255, 0), "Blue": (0, 0, 255), "Cyan": (0, 255, 255),
    "Magenta": (255, 0, 255), "Yellow": (255, 255, 0), "White": (255, 255, 255),
    "Black": (0, 0, 0), "Gray": (136, 136, 136), "LightGray": (204, 204, 204),
    "DarkGray": (68, 68, 68),
}
FLUTTER_NAMED = {
    "purple": (156, 39, 176), "deepPurple": (103, 58, 183), "indigo": (63, 81, 181),
    "blue": (33, 150, 243), "lightBlue": (3, 169, 244), "cyan": (0, 188, 212),
    "teal": (0, 150, 136), "green": (76, 175, 80), "lightGreen": (139, 195, 74),
    "lime": (205, 220, 57), "yellow": (255, 235, 59), "amber": (255, 193, 7),
    "orange": (255, 152, 0), "deepOrange": (255, 87, 34), "red": (244, 67, 54),
    "pink": (233, 30, 99), "purpleAccent": (224, 64, 251), "deepPurpleAccent": (124, 77, 255),
    "indigoAccent": (83, 109, 254), "blueAccent": (68, 138, 255), "cyanAccent": (24, 255, 255),
    "pinkAccent": (255, 64, 129), "white": (255, 255, 255), "black": (0, 0, 0),
    "grey": (158, 158, 158), "white10": (255, 255, 255), "white24": (255, 255, 255),
}

COLOR_RE = re.compile(
    r"IM_COL32\(\s*(?P<c32>\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*\d+)?)\s*\)"
    r"|ImVec4\(\s*(?P<v4>[\d.]+f?\s*,\s*[\d.]+f?\s*,\s*[\d.]+f?(?:\s*,\s*[\d.]+f?)?)\s*\)"
    r"|ImColor\(\s*(?P<imc>\d+\s*,\s*\d+\s*,\s*\d+)"
    r"|Color\(\s*0x(?P<argb>[0-9A-Fa-f]{8})\s*\)"
    r"|Color\(\s*red:\s*(?P<sr>[\d.]+)\s*,\s*green:\s*(?P<sg>[\d.]+)\s*,\s*blue:\s*(?P<sb>[\d.]+)"
    r"|Color\(\s*hex:\s*\"?#?(?P<shex>[0-9A-Fa-f]{6})"
    r"|[\"']#(?P<h8>[0-9A-Fa-f]{8})[\"']"
    r"|[\"']#(?P<h6>[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})[\"']"
    r"|\bColors\.(?P<flutter>[a-zA-Z]+\d*)"
    r"|\bColor\.(?P<cname>[A-Za-z]+)\b"
    r"|(?<![\w.])\.(?P<swift>red|orange|yellow|green|mint|teal|cyan|blue|indigo|purple|pink|"
    r"brown|gray|white|black)\b"
    r"|(?:Color|Fill|Background|BorderBrush|Foreground|Stroke|color)\s*[=:]\s*\"(?P<named>[A-Za-z]+)\"")
ALPHA_RE = re.compile(r"^\s*\.(?:withOpacity|opacity|withAlpha)\(\s*([\d.]+)f?\s*\)"
                      r"|^\s*\.copy\(\s*alpha\s*=\s*([\d.]+)f?\s*\)")


def app_colors(snippet: str, framework: str = "") -> list:
    """Colors in order of appearance as (r, g, b, a)."""
    out = []
    for m in COLOR_RE.finditer(snippet):
        g = m.groupdict()
        c = None
        if g["c32"]:
            nums = [int(x) for x in re.findall(r"\d+", g["c32"])]
            c = (nums[0], nums[1], nums[2], (nums[3] if len(nums) > 3 else 255) / 255.0)
        elif g["v4"]:
            nums = [float(x.rstrip("f")) for x in re.findall(r"[\d.]+f?", g["v4"])]
            if all(v <= 1.0 for v in nums):
                c = (int(nums[0] * 255), int(nums[1] * 255), int(nums[2] * 255),
                     nums[3] if len(nums) > 3 else 1.0)
        elif g["imc"]:
            nums = [int(x) for x in re.findall(r"\d+", g["imc"])]
            c = (nums[0], nums[1], nums[2], 1.0)
        elif g["argb"]:
            h = g["argb"]
            c = (int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16), int(h[0:2], 16) / 255.0)
        elif g["sr"]:
            c = (int(float(g["sr"]) * 255), int(float(g["sg"]) * 255), int(float(g["sb"]) * 255),
                 1.0)
        elif g["shex"]:
            h = g["shex"]
            c = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
        elif g["h8"]:
            h = g["h8"]  # XAML and Qt write #AARRGGBB
            c = (int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16), int(h[0:2], 16) / 255.0)
        elif g["h6"]:
            c = web.parse_color("#" + g["h6"])
        elif g["flutter"]:
            rgb = FLUTTER_NAMED.get(g["flutter"])
            if rgb:
                c = (rgb[0], rgb[1], rgb[2], 1.0)
        elif g["cname"]:
            rgb = COMPOSE_NAMED.get(g["cname"]) or SWIFT_NAMED.get(g["cname"])
            if rgb:
                c = (rgb[0], rgb[1], rgb[2], 1.0)
        elif g["swift"]:
            rgb = SWIFT_NAMED[g["swift"]]
            c = (rgb[0], rgb[1], rgb[2], 1.0)
        elif g["named"]:
            c = web.parse_color(g["named"])
        if c is None:
            continue
        am = ALPHA_RE.match(snippet[m.end():m.end() + 40])
        if am:
            c = (c[0], c[1], c[2], float(am.group(1) or am.group(2)))
        out.append(c)
    return out


@dataclass
class AppDoc:
    path: Path
    text: str
    framework: str
    web: object = None   # scan_web.WebDoc for markup-based app UIs

    def line(self, offset: int) -> int:
        return line_of(self.text, offset)

    def window(self, offset: int, lines_before: int, lines_after: int) -> str:
        rows = self.text.split("\n")
        ln = self.line(offset) - 1
        return "\n".join(rows[max(0, ln - lines_before): ln + lines_after + 1])


def detect_framework(path: Path, text: str) -> str:
    ext = path.suffix.lower()
    if ext in (".xaml", ".axaml"):
        return "xaml"
    if ext == ".qml":
        return "qml"
    if ext == ".swift":
        return "swiftui"
    if ext in (".kt", ".kts"):
        return "compose"
    if ext == ".dart":
        return "flutter"
    if ext in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh"):
        return "imgui"
    if ext in (".jsx", ".tsx", ".js", ".ts") and "react-native" in text:
        return "react-native"
    return "markup"


def load(path: Path) -> AppDoc:
    text = read_text(path)
    fw = detect_framework(path, text)
    webdoc = web.parse_web(text, path) if fw in ("markup", "react-native") else None
    return AppDoc(path, text, fw, webdoc)


def sniff(path: Path, head: bytes) -> int:
    ext = path.suffix.lower()
    if ext in (".xaml", ".axaml", ".qml"):
        return 90
    if ext == ".swift":
        return 90 if b"SwiftUI" in head else 20
    if ext in (".kt", ".kts"):
        return 90 if (b"@Composable" in head or b"androidx.compose" in head) else 0
    if ext == ".dart":
        return 90 if (b"package:flutter" in head or b"Widget build(" in head) else 0
    if ext in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh"):
        return 90 if b"ImGui::" in head else 0
    if ext in (".jsx", ".tsx", ".js", ".ts") and b"react-native" in head:
        return 85
    return 0


register_domain(DOMAIN, load=load, sniff=sniff, extensions=EXTENSIONS,
                description="Desktop and mobile UI code: XAML, SwiftUI, Compose, Flutter, QML, "
                            "ImGui, React Native, HTML app shells")


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

RADIUS_PATTERNS = (
    re.compile(r"CornerRadius=\"([^\"]+)\""),
    re.compile(r"cornerRadius:\s*(\d+(?:\.\d+)?)"),
    re.compile(r"\.cornerRadius\(\s*(\d+(?:\.\d+)?)"),
    re.compile(r"RoundedCornerShape\(\s*(?:size\s*=\s*)?(\d+(?:\.\d+)?)\.dp\s*\)"),
    re.compile(r"(?:BorderRadius|Radius)\.circular\(\s*(\d+(?:\.\d+)?)"),
    re.compile(r"borderRadius:\s*(\d+(?:\.\d+)?)"),
    re.compile(r"\b(?:Window|Child|Frame|Popup|Scrollbar|Grab|Tab)Rounding\s*=\s*(\d+(?:\.\d+)?)f?"),
    re.compile(r"ImGuiStyleVar_\w*Rounding\s*,\s*(\d+(?:\.\d+)?)f?"),
)
QML_RADIUS = re.compile(r"^\s*radius:\s*(\d+(?:\.\d+)?)\s*$", re.M)


def radius_values(doc: AppDoc) -> list:
    values = []
    for pat in RADIUS_PATTERNS:
        for m in pat.finditer(doc.text):
            raw = m.group(1)
            parts = {p.strip() for p in raw.split(",")}
            if len(parts) != 1:
                values.append((raw, doc.line(m.start())))
                continue
            try:
                values.append((float(parts.pop()), doc.line(m.start())))
            except ValueError:
                values.append((raw, doc.line(m.start())))
    if doc.framework == "qml":
        for m in QML_RADIUS.finditer(doc.text):
            values.append((float(m.group(1)), doc.line(m.start())))
    if doc.web is not None:
        for node in doc.web.nodes():
            for c in node.tw():
                r = web.tw_radius_px(c)
                if r is not None and r < 9999:
                    values.append((r, node.line))
        for r in web.all_css_rules(doc.web):
            v = web.first_radius_px(r.decls.get("border-radius"))
            if v is not None and v < 9999:
                values.append((v, r.line))
    return values


@rule("app.uniform-radius", recognition="app-uniform-corner-radius", severity=3)
def r_uniform_radius(doc: AppDoc):
    """Every surface uses one large corner radius."""
    vals = radius_values(doc)
    nums = [v for v, _ in vals if isinstance(v, float) and v > 0]
    if len(nums) < UNIFORM_RADIUS_MIN_COUNT or len(nums) != len(vals):
        return
    if len(set(nums)) == 1 and nums[0] >= UNIFORM_RADIUS_MIN_VALUE:
        yield hit(f"line {vals[0][1]}", f"{len(nums)} corner radii, all {nums[0]:g}", 0.85)


TILE_NAME = r"[A-Z]\w*(?:Card|Tile|Stat|Metric|Feature|Kpi|KPI|Widget|Cell)|Border|BeginChild"
TILE_CALL_RE = re.compile(r"(?<![\w.])((?:\w+::)?(?:" + TILE_NAME + r"))\s*\(([^\n]*)")
TILE_TAG_RE = re.compile(r"<\s*((?:\w+:)?(?:" + TILE_NAME + r"))\b([^>\n]*)")
GRID_RE = re.compile(r"\b(LazyVGrid|LazyHGrid|LazyVerticalGrid|LazyHorizontalGrid|UniformGrid|"
                     r"GridView\.count|GridView\.builder|GridLayout|BeginTable)\b")
GRID_ITEMS_RE = re.compile(r"\b(ForEach|items\(|itemBuilder|ItemTemplate|Repeater|for\s*\()")
GRID_TILE_RE = re.compile(r"\b[A-Z]\w*(Card|Tile|Stat|Metric|Feature|Kpi|Cell)\s*[({]")


def _normalize_call(rest: str) -> str:
    s = re.sub(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", "S", rest)
    s = re.sub(r"\b\d+(?:\.\d+)?[a-z]*\b", "N", s)
    return " ".join(s.split())


@rule("app.identical-tile-grid", recognition="app-identical-tile-grid", severity=3)
def r_tile_grid(doc: AppDoc):
    """Grid of identical tiles that differ only in label and number."""
    groups = {}
    matches = list(TILE_CALL_RE.finditer(doc.text)) + list(TILE_TAG_RE.finditer(doc.text))
    for m in matches:
        name, rest = m.group(1), m.group(2)
        if '"' not in rest and "'" not in rest and "=" not in rest:
            continue
        key = name + " " + _normalize_call(rest)
        groups.setdefault(key, []).append(doc.line(m.start()))
    for key, lines in groups.items():
        if len(lines) >= TILE_REPEAT_MIN:
            yield hit(f"line {lines[0]}", f"{len(lines)} identical tiles: {key[:70]}", 0.85)
            return
    for m in GRID_RE.finditer(doc.text):
        window = doc.text[m.start(): m.start() + GRADIENT_WINDOW_CHARS]
        if GRID_ITEMS_RE.search(window) and GRID_TILE_RE.search(window):
            tile = GRID_TILE_RE.search(window).group(0).rstrip("({ ")
            yield hit(f"line {doc.line(m.start())}", f"{m.group(1)} repeating one template "
                      f"tile ({tile})", 0.7)
            return
    if doc.web is not None:
        for node in doc.web.nodes():
            kids = node.elements()
            if len(kids) >= TILE_REPEAT_MIN and len({web._shape(k) for k in kids}) == 1 and \
                    len(web._shape(kids[0])) > 2:
                yield hit(f"line {node.line}", f"{len(kids)} identical tiles in one container",
                          0.7)
                return


GRADIENT_RE = re.compile(
    r"\b(LinearGradient|RadialGradient|AngularGradient|EllipticalGradient|LinearGradientBrush|"
    r"RadialGradientBrush|Brush\.(?:horizontal|vertical|linear|radial|sweep)Gradient|"
    r"AddRectFilledMultiColor|SweepGradient|Gradient)\b")


def _gradient_window(text: str, start: int) -> str:
    end_tag = re.compile(r"</\s*(LinearGradientBrush|RadialGradientBrush)\s*>")
    m = end_tag.search(text, start)
    if m and m.start() - start < GRADIENT_WINDOW_CHARS * 2:
        return text[start:m.end()]
    i = start
    while i < len(text) and text[i] not in "({":
        i += 1
    if i >= len(text) or i - start > 60:
        return text[start:start + GRADIENT_WINDOW_CHARS]
    depth, j = 0, i
    while j < len(text):
        if text[j] in "({":
            depth += 1
        elif text[j] in ")}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return text[start:j + 1]


@rule("app.gradient-header", recognition="app-purple-gradient-header", severity=4)
def r_gradient_header(doc: AppDoc):
    """Purple/indigo to blue gradient on a header or hero surface."""
    seen = set()
    for m in GRADIENT_RE.finditer(doc.text):
        ln = doc.line(m.start())
        if ln in seen:
            continue
        colors = app_colors(_gradient_window(doc.text, m.start()), doc.framework)
        if web.is_purple_blue_gradient(colors):
            seen.add(ln)
            yield hit(f"line {ln}", f"{m.group(1)} with {len(colors)} purple/blue stops", 0.85)
    if doc.web is not None:
        for line, ev in web.purple_gradients(doc.web):
            yield hit(f"line {line}", ev, 0.85)


def _group(colors):
    """Hue group of the first color in a tight snippet (neutral included, so a
    gray capsule with a gray dot is still the same three-carrier chip)."""
    return web.hue_group(colors[0]) if colors else None


def _dots(doc: AppDoc):
    t = doc.text
    out = []
    for m in re.finditer(r"Circle\(\)", t):
        win = doc.window(m.start(), 0, 3)
        size = re.search(r"\.frame\(\s*width:\s*(\d+(?:\.\d+)?)", win)
        fill = re.search(r"\.fill\(([^)]*\)?)\)", win)
        if size and float(size.group(1)) <= DOT_MAX and fill:
            out.append((doc.line(m.start()), _group(app_colors(fill.group(1)))))
    for m in re.finditer(r"CircleShape", t):
        win = doc.window(m.start(), 2, 2)
        size = re.search(r"\.size\(\s*(\d+(?:\.\d+)?)\.dp\s*\)", win)
        bg = re.search(r"\.background\(([^\n]*)", win)
        if size and float(size.group(1)) <= DOT_MAX and bg:
            out.append((doc.line(m.start()), _group(app_colors(bg.group(1)))))
    for m in re.finditer(r"<Ellipse\b[^>]*>", t):
        tag = m.group(0)
        w = re.search(r"Width=\"(\d+(?:\.\d+)?)\"", tag)
        fill = re.search(r"Fill=\"([^\"]+)\"", tag)
        if w and float(w.group(1)) <= DOT_MAX and fill:
            out.append((doc.line(m.start()), _group(app_colors(f'Fill="{fill.group(1)}"'))))
    for m in re.finditer(r"BoxShape\.circle", t):
        win = doc.window(m.start(), 4, 2)
        w = re.search(r"width:\s*(\d+(?:\.\d+)?)", win)
        col = re.search(r"color:\s*([^\n]*)", win)
        if w and float(w.group(1)) <= DOT_MAX and col:
            out.append((doc.line(m.start()), _group(app_colors(col.group(1)))))
    if doc.framework == "qml":
        for m in re.finditer(r"Rectangle\s*\{([^{}]*)\}", t):
            body = m.group(1)
            w = re.search(r"width:\s*(\d+)", body)
            if w and int(w.group(1)) <= DOT_MAX and "radius" in body:
                col = re.search(r"\bcolor:\s*([^\n;]*)", body)
                if col:
                    out.append((doc.line(m.start()), _group(app_colors("color: " + col.group(1)))))
    return out


def _pill_outlines(doc: AppDoc):
    t = doc.text
    out = []
    for m in re.finditer(r"Capsule\(\)\s*\.stroke(?:Border)?\(([^\n]*)", t):
        out.append((doc.line(m.start()), _group(app_colors(m.group(1)))))
    for m in re.finditer(r"RoundedCornerShape\(\s*(?:percent\s*=\s*)?(50|100)\s*\)", t):
        win = doc.window(m.start(), 3, 3)
        b = re.search(r"(?:\.border\(\s*[\d.]+\.dp\s*,|BorderStroke\(\s*[\d.]+\.dp\s*,)([^\n]*)",
                      win)
        if b:
            out.append((doc.line(m.start()), _group(app_colors(b.group(1)))))
    for m in re.finditer(r"<Border\b[^>]*>", t):
        tag = m.group(0)
        cr = re.search(r"CornerRadius=\"(\d+(?:\.\d+)?)\"", tag)
        bb = re.search(r"BorderBrush=\"([^\"]+)\"", tag)
        if cr and float(cr.group(1)) >= PILL_RADIUS_MIN and bb:
            out.append((doc.line(m.start()), _group(app_colors(f'BorderBrush="{bb.group(1)}"'))))
    for m in re.finditer(r"StadiumBorder|BorderRadius\.circular\(\s*(\d{2,})", t):
        if m.group(1) and int(m.group(1)) < 99:
            continue
        win = doc.window(m.start(), 4, 4)
        b = re.search(r"Border\.all\(\s*color:\s*([^\n]*)", win)
        if b:
            out.append((doc.line(m.start()), _group(app_colors(b.group(1)))))
    if doc.framework == "qml":
        for m in re.finditer(r"radius:\s*height\s*/\s*2", t):
            win = doc.window(m.start(), 4, 4)
            b = re.search(r"border\.color:\s*([^\n;]*)", win)
            if b:
                out.append((doc.line(m.start()), _group(app_colors("color: " + b.group(1)))))
    return out


@rule("app.pill-dot-chip", recognition="app-pill-dot-status-chip", severity=4)
def r_pill_dot(doc: AppDoc):
    """Capsule chip with a dot inside and an outline in the dot's color."""
    dots = [d for d in _dots(doc) if d[1]]
    seen = set()
    for pl, pg in _pill_outlines(doc):
        if not pg:
            continue
        for dl, dg in dots:
            if dg == pg and abs(dl - pl) <= PILL_WINDOW_LINES and pl not in seen:
                seen.add(pl)
                yield hit(f"line {pl}", f"{pg} capsule outline + {pg} dot (line {dl})", 0.85)
    if doc.web is not None:
        for node, group in web.pill_dot_badges(doc.web):
            yield hit(f"line {node.line}", f"{group} pill + dot + outline: {node.snippet()}", 0.9)


BLUR_RE = re.compile(r"\.(?:ultraThin|thin|regular|thick)Material\b|\.blur\(|BackdropFilter|"
                     r"ImageFilter\.blur|AcrylicBrush|BlurEffect|FastBlur|MultiEffect")
STROKE_RE = re.compile(r"stroke|border|BorderBrush|Border\.all", re.I)


def _white_alpha(colors) -> bool:
    return any(c[0] > 240 and c[1] > 240 and c[2] > 240 and
               GLASS_ALPHA_RANGE[0] <= c[3] <= GLASS_ALPHA_RANGE[1] for c in colors)


@rule("app.glass-panel", recognition="app-glass-acrylic-panel", severity=3)
def r_glass(doc: AppDoc):
    """Blur or material backdrop + translucent white fill + white hairline stroke."""
    seen = set()
    for m in BLUR_RE.finditer(doc.text):
        win = doc.window(m.start(), GLASS_WINDOW_LINES, GLASS_WINDOW_LINES)
        fill = _white_alpha(app_colors(win))
        if "AcrylicBrush" in m.group(0):
            to = re.search(r"TintOpacity=\"([\d.]+)\"", win)
            fill = fill or bool(to and float(to.group(1)) <= 0.6)
        stroke_lines = [l for l in win.split("\n") if STROKE_RE.search(l)]
        stroke = any(any(c[0] > 240 and c[1] > 240 and c[2] > 240 for c in app_colors(l))
                     for l in stroke_lines)
        ln = doc.line(m.start())
        if fill and stroke and not any(abs(ln - s) <= GLASS_WINDOW_LINES for s in seen):
            seen.add(ln)
            yield hit(f"line {ln}", f"{m.group(0).strip('.(')} + white/alpha fill + white stroke",
                      0.85)
    if doc.web is not None:
        for line, ev in web.glass_hits(doc.web):
            yield hit(f"line {line}", ev, 0.9)


APP_SPARKLE_PATTERNS = (
    re.compile(r"systemName:\s*\"(?:sparkles?|wand\.and\.stars(?:\.inverse)?|"
               r"sparkle\.magnifyingglass)\""),
    re.compile(r"\bIcons\.(?:Filled|Outlined|Rounded|Sharp|TwoTone|Default)\.AutoAwesome\w*"),
    re.compile(r"\bIcons\.auto_awesome\w*"),
    re.compile(r"\bICON_(?:FA|MD|MDI|LC)_(?:WAND_MAGIC_SPARKLES|SPARKLES|STARS|AUTO_AWESOME)\b"),
    re.compile(r"icon\.name:\s*\"[^\"]*sparkle", re.I),
    re.compile("\u2728"),
)


@rule("app.sparkle-ai", recognition="app-sparkle-ai-action", severity=3)
def r_sparkle(doc: AppDoc):
    """Sparkles or magic wand icon as the label for an AI action."""
    lines = set()
    for pat in APP_SPARKLE_PATTERNS:
        for m in pat.finditer(doc.text):
            ln = doc.line(m.start())
            if ln not in lines:
                lines.add(ln)
                token = m.group(0) if m.group(0).isascii() else "U+2728 sparkles emoji"
                yield hit(f"line {ln}", token, 0.85)
    if doc.web is not None:
        for ln, token, conf in web.sparkle_hits(doc.text):
            if ln not in lines:
                lines.add(ln)
                yield hit(f"line {ln}", token, conf)


def _colorful(colors) -> bool:
    return any(web.hsl(c)[1] >= 0.45 and 0.2 <= web.hsl(c)[2] <= 0.85 for c in colors)


def native_glows(doc: AppDoc) -> list:
    t = doc.text
    glows = []
    for m in re.finditer(r"\.shadow\(\s*color:\s*([^\n]*?),\s*radius:\s*(\d+(?:\.\d+)?)"
                         r"(?:\s*,\s*x:\s*(-?[\d.]+)\s*,\s*y:\s*(-?[\d.]+))?", t):
        offs = [float(v) for v in (m.group(3), m.group(4)) if v is not None]
        if float(m.group(2)) >= GLOW_MIN_RADIUS and all(abs(o) <= 1 for o in offs) and \
                _colorful(app_colors(m.group(1))):
            glows.append((doc.line(m.start()), ".shadow(color:, radius:) zero offset"))
    for m in re.finditer(r"\.shadow\(([^\n]*(?:ambientColor|spotColor)[^\n]*)", t):
        if _colorful(app_colors(m.group(1))):
            glows.append((doc.line(m.start()), "Modifier.shadow with colored ambient/spot"))
    for m in re.finditer(r"<DropShadowEffect\b[^>]*>", t):
        tag = m.group(0)
        depth = re.search(r"ShadowDepth=\"([\d.]+)\"", tag)
        blur = re.search(r"BlurRadius=\"([\d.]+)\"", tag)
        if depth and float(depth.group(1)) == 0 and blur and \
                float(blur.group(1)) >= GLOW_MIN_RADIUS and _colorful(app_colors(tag)):
            glows.append((doc.line(m.start()), "DropShadowEffect ShadowDepth=0"))
    for m in re.finditer(r"BoxShadow\(", t):
        body = _gradient_window(t, m.start())
        blur = re.search(r"blurRadius:\s*([\d.]+)", body)
        off = re.search(r"offset:\s*(Offset\.zero|Offset\(\s*0(?:\.0)?\s*,\s*0(?:\.0)?\s*\))", body)
        has_off = "offset:" in body
        if blur and float(blur.group(1)) >= GLOW_MIN_RADIUS and (off or not has_off) and \
                _colorful(app_colors(body)):
            glows.append((doc.line(m.start()), "BoxShadow zero offset, colored"))
    for m in re.finditer(r"\b(?:DropShadow|Glow)\s*\{([^{}]*)\}", t):
        body = m.group(1)
        if not re.search(r"(horizontalOffset|verticalOffset):\s*[1-9]", body) and \
                _colorful(app_colors(body)):
            glows.append((doc.line(m.start()), "QML DropShadow/Glow, colored"))
    return glows


@rule("app.neon-glow", recognition="app-neon-glow-controls", severity=3)
def r_neon(doc: AppDoc):
    """Colored zero-offset glows on several controls."""
    glows = native_glows(doc)
    if doc.web is not None:
        glows += web.neon_glows(doc.web)
    if len(glows) >= GLOW_MIN_COUNT:
        for line, ev in glows[:10]:
            yield hit(f"line {line}", ev, 0.8)


GREETING_RE = re.compile(r"\b(Welcome back|Good (?:morning|afternoon|evening)|"
                         r"(?:Hello|Hi|Hey),\s*[A-Z$\\{(][^\"\n]{0,24}!)")
DELTA_RE = re.compile("(?:^|[\\s\"'>(])([+\\-\u2191\u2193\u25b2\u25bc]\\s?\\d+(?:\\.\\d+)?\\s?%)")


@rule("app.greeting-stat-row", recognition="app-greeting-stat-dashboard", severity=3)
def r_greeting(doc: AppDoc):
    """'Welcome back' greeting over a row of percent-delta stat tiles."""
    g = GREETING_RE.search(doc.text)
    if not g:
        return
    deltas = DELTA_RE.findall(doc.text)
    if len(deltas) >= STAT_DELTA_MIN:
        shown = ", ".join(d.encode("ascii", "replace").decode() for d in deltas[:4])
        yield hit(f"line {doc.line(g.start())}", f"'{g.group(0)[:30]}' + {len(deltas)} "
                  f"delta tiles ({shown})", 0.8)
