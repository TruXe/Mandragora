"""Web domain: HTML, JSX/TSX, Vue, Svelte, Astro, Blade templates and CSS.

The loader builds a tolerant element tree (stdlib html.parser) plus a list of
CSS rules from .css files, <style> blocks and inline styles. Rules read
Tailwind utility classes and plain CSS declarations side by side.

Helpers in this module (color parsing, Tailwind class parsing, gradient and
pill checks) are reused by scan_app.py for markup-based app UIs.
"""

from __future__ import annotations

import colorsys
import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from scanners.core import hit, line_of, read_text, register_domain, rule

DOMAIN = "web"
EXTENSIONS = (".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".css", ".scss",
              ".blade.php")

# ---------------------------------------------------------------- thresholds
# A status dot is drawn at 6 to 10 px. Larger round children are avatars/icons.
DOT_MAX_PX = 10
# Radii at or above this many px render as a full pill on any badge height.
PILL_RADIUS_PX = 50
# Saturation floor for a color to count as "colored" (HSL, 0..1). Grays sit below.
COLOR_SAT_MIN = 0.30
# Hue band (degrees) for the purple/indigo/violet half of the slop gradient.
PURPLE_HUE_RANGE = (235.0, 335.0)
# Hue band (degrees) for the whole blue-to-purple family of the slop gradient.
BLUE_PURPLE_HUE_RANGE = (195.0, 335.0)
# Two stops closer than this many degrees are one hue, a tonal ramp is fine.
GRADIENT_MIN_HUE_SPREAD = 20.0
# Glass panels use white at 4..45 percent opacity. Above that it is a solid card.
GLASS_ALPHA_RANGE = (0.04, 0.45)
# rounded-2xl is 16 px; shadow-xl blur is 25 px. The rule asks for both at once.
HEAVY_RADIUS_PX = 16
HEAVY_SHADOW_BLUR_PX = 20
# Heavy containers must be at least this many and this share of all containers.
HEAVY_MIN_COUNT = 3
HEAVY_MIN_RATIO = 0.5
# Identical sibling cards needed before a feature row reads as a template.
CARD_ROW_MIN = 3
# Icon tiles are small squares; above 80 px they are illustrations.
ICON_TILE_MAX_PX = 80
# A glow is a zero-offset shadow with at least this much blur.
GLOW_MIN_BLUR_PX = 8
# One glow can be a focus ring; two or more is a theme.
GLOW_MIN_COUNT = 2
# Logos needed next to a "trusted by" line to count as a logo strip.
LOGO_STRIP_MIN = 3
# Bento grids: at least this many tiles in a 3+ column grid.
BENTO_MIN_TILES = 4
# Ancestor levels searched when relating a heading or phrase to its section.
SECTION_LEVELS = 3

TW_FAMILIES = ("slate gray zinc neutral stone red orange amber yellow lime green emerald teal "
               "cyan sky blue indigo violet purple fuchsia pink rose").split()
# Families folded into one hue group so "same hue" comparisons are fair.
HUE_GROUP = {
    "slate": "neutral", "gray": "neutral", "zinc": "neutral", "neutral": "neutral",
    "stone": "neutral", "red": "red", "rose": "red", "orange": "orange", "amber": "yellow",
    "yellow": "yellow", "lime": "green", "green": "green", "emerald": "green", "teal": "teal",
    "cyan": "teal", "sky": "blue", "blue": "blue", "indigo": "indigo", "violet": "purple",
    "purple": "purple", "fuchsia": "pink", "pink": "pink", "white": "white", "black": "black",
}
GRADIENT_FAMILIES = {"purple", "violet", "indigo", "fuchsia", "blue", "sky", "pink"}
PURPLE_FAMILIES = {"purple", "violet", "indigo", "fuchsia"}
NEUTRAL_FAMILIES = {"slate", "gray", "zinc", "neutral", "stone", "white", "black"}

TW_RADIUS = {"rounded-none": 0, "rounded-sm": 2, "rounded": 4, "rounded-md": 6, "rounded-lg": 8,
             "rounded-xl": 12, "rounded-2xl": 16, "rounded-3xl": 24, "rounded-4xl": 32,
             "rounded-full": 9999}
TW_SHADOW_BLUR = {"shadow-sm": 2, "shadow": 3, "shadow-md": 6, "shadow-lg": 15, "shadow-xl": 25,
                  "shadow-2xl": 50}

NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 128, 0),
    "blue": (0, 0, 255), "purple": (128, 0, 128), "violet": (238, 130, 238),
    "indigo": (75, 0, 130), "magenta": (255, 0, 255), "fuchsia": (255, 0, 255),
    "cyan": (0, 255, 255), "aqua": (0, 255, 255), "pink": (255, 192, 203),
    "orange": (255, 165, 0), "yellow": (255, 255, 0), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "lime": (0, 255, 0), "teal": (0, 128, 128), "navy": (0, 0, 128),
    "royalblue": (65, 105, 225), "dodgerblue": (30, 144, 255), "deepskyblue": (0, 191, 255),
    "blueviolet": (138, 43, 226), "mediumpurple": (147, 112, 219), "slateblue": (106, 90, 205),
    "darkviolet": (148, 0, 211), "hotpink": (255, 105, 180), "limegreen": (50, 205, 50),
    "crimson": (220, 20, 60), "gold": (255, 215, 0), "transparent": None,
}
# Tailwind 500 shades, used when a family must become a concrete color.
TW_500 = {
    "slate": (100, 116, 139), "gray": (107, 114, 128), "zinc": (113, 113, 122),
    "neutral": (115, 115, 115), "stone": (120, 113, 108), "red": (239, 68, 68),
    "orange": (249, 115, 22), "amber": (245, 158, 11), "yellow": (234, 179, 8),
    "lime": (132, 204, 22), "green": (34, 197, 94), "emerald": (16, 185, 129),
    "teal": (20, 184, 166), "cyan": (6, 182, 212), "sky": (14, 165, 233),
    "blue": (59, 130, 246), "indigo": (99, 102, 241), "violet": (139, 92, 246),
    "purple": (168, 85, 247), "fuchsia": (217, 70, 239), "pink": (236, 72, 153),
    "rose": (244, 63, 94), "white": (255, 255, 255), "black": (0, 0, 0),
}

HERO_VERB_RE = re.compile(
    r"\b(supercharg\w*|elevat\w*|unlock\w*|unleash\w*|transform\w*|empower\w*|"
    r"revolutioni[sz]\w*|reimagin\w*|redefin\w*|turbocharg\w*|skyrocket\w*|amplif\w*|"
    r"ignit\w*|level up|10x)\b", re.I)
TRUST_RE = re.compile(
    r"\b(trusted|loved|used|chosen|relied on|backed|powering|adopted)\s+by\b|"
    r"\bas seen (on|in)\b|"
    r"\bjoin (over |more than )?[\d,.]+\s*k?\+?\s+(teams|companies|developers|customers|users)\b",
    re.I)
PLACEHOLDER_BRANDS = re.compile(
    r"^\s*(acme( corp| inc)?|globex|initech|umbrella( corp)?|hooli|soylent|stark industries|"
    r"wayne enterprises|wonka|logoipsum|vandelay|cyberdyne|massive dynamic|pied piper|"
    r"company\s*\d*|brand\s*\d*|logo\s*\d*|client\s*\d*)\s*$", re.I)
SPARKLE_PATTERNS = (
    re.compile(r"<\s*Sparkles(?:Icon)?\b"),
    re.compile(r"\bSparkles(?:Icon)\b"),
    re.compile(r"\blucide-sparkles?\b"),
    re.compile(r"\b(?:data-lucide|name|icon|data-icon)\s*=\s*[\"'][^\"']*sparkle", re.I),
    re.compile(r"\bfa-(?:wand-magic-)?sparkles\b"),
    re.compile(r"\bbi-stars\b"),
    re.compile(r"\bph-sparkle\b"),
    re.compile(r"\bauto_awesome\b"),
    re.compile(r"heroicons[^\"'\s]*sparkles"),
    re.compile("✨"),
)
AI_WORD_RE = re.compile(r"\bAI\b|\bai-|\bgenerat\w+|\bmagic\b", re.I)

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "source", "track", "wbr", "param"}
CONTAINER_TAGS = {"div", "section", "article", "aside", "li", "form", "header", "footer",
                  "main", "nav", "figure", "details", "dialog", "a", "button", "label"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


# --------------------------------------------------------------------------
# Colors
# --------------------------------------------------------------------------

def _clamp8(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _oklch_to_rgb(l, c, h):
    """OKLCH (L 0..1, C, H degrees) to sRGB 0..255 (Ottosson's matrices)."""
    a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.2914855480 * b
    l3, m3, s3 = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
           -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
           -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3)

    def gamma(x):
        x = max(0.0, min(1.0, x))
        return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055

    return tuple(_clamp8(gamma(x) * 255) for x in lin)


def _num(token: str, scale: float = 255.0) -> float:
    token = token.strip()
    if token.endswith("%"):
        return float(token[:-1]) / 100.0 * scale
    return float(token)


COLOR_TOKEN_RE = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)|oklch\([^)]*\)|\b[a-zA-Z]+\b")


def parse_color(token: str):
    """Return (r, g, b, a) or None for one CSS color token."""
    t = token.strip().lower()
    if t.startswith("#"):
        h = t[1:]
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", h):
            return None
        a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a
    m = re.match(r"(rgba?|hsla?|oklch)\((.*)\)$", t)
    if m:
        parts = [p for p in re.split(r"[\s,/]+", m.group(2).strip()) if p]
        try:
            if m.group(1).startswith("rgb") and len(parts) >= 3:
                a = _num(parts[3], 1.0) if len(parts) > 3 else 1.0
                return (_clamp8(_num(parts[0])), _clamp8(_num(parts[1])),
                        _clamp8(_num(parts[2])), a)
            if m.group(1).startswith("hsl") and len(parts) >= 3:
                hue = float(parts[0].replace("deg", ""))
                s, l = _num(parts[1], 1.0), _num(parts[2], 1.0)
                r, g, b = colorsys.hls_to_rgb((hue % 360) / 360.0, l, s)
                a = _num(parts[3], 1.0) if len(parts) > 3 else 1.0
                return _clamp8(r * 255), _clamp8(g * 255), _clamp8(b * 255), a
            if m.group(1) == "oklch" and len(parts) >= 3:
                l = _num(parts[0], 1.0) if parts[0].endswith("%") else float(parts[0])
                r, g, b = _oklch_to_rgb(l, float(parts[1]), float(parts[2].replace("deg", "")))
                a = _num(parts[3], 1.0) if len(parts) > 3 else 1.0
                return r, g, b, a
        except ValueError:
            return None
        return None
    rgb = NAMED_COLORS.get(t)
    if rgb:
        return rgb[0], rgb[1], rgb[2], 1.0
    return None


def colors_in(text: str) -> list:
    out = []
    for m in COLOR_TOKEN_RE.finditer(text or ""):
        c = parse_color(m.group(0))
        if c is not None:
            out.append(c)
    return out


def hsl(color):
    r, g, b = color[0] / 255.0, color[1] / 255.0, color[2] / 255.0
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0, s, l


def hue_group(color) -> str:
    """Bucket an RGB(A) color into the same names HUE_GROUP uses."""
    h, s, l = hsl(color)
    if l > 0.95:
        return "white"
    if l < 0.06:
        return "black"
    if s < 0.15:
        return "neutral"
    bands = ((15, "red"), (40, "orange"), (70, "yellow"), (165, "green"), (195, "teal"),
             (232, "blue"), (252, "indigo"), (290, "purple"), (345, "pink"), (361, "red"))
    for top, name in bands:
        if h < top:
            return name
    return "red"


def is_colored(color) -> bool:
    h, s, l = hsl(color)
    return s >= COLOR_SAT_MIN and 0.12 <= l <= 0.92


def _in_band(h, band):
    return band[0] <= h <= band[1]


def is_purple_blue_gradient(colors) -> bool:
    """True when the stops are all blue/indigo/violet/purple/pink hues, at least
    one sits in the purple half, and the hues actually change."""
    stops = [c for c in colors if c is not None and is_colored(c) and (len(c) < 4 or c[3] > 0.1)]
    if len(stops) < 2:
        return False
    hues = [hsl(c)[0] for c in stops]
    if not all(_in_band(h, BLUE_PURPLE_HUE_RANGE) for h in hues):
        return False
    if not any(_in_band(h, PURPLE_HUE_RANGE) for h in hues):
        return False
    return max(hues) - min(hues) >= GRADIENT_MIN_HUE_SPREAD


def is_purple_blue_families(families) -> bool:
    fams = [f for f in families if f]
    if len(fams) < 2 or not all(f in GRADIENT_FAMILIES for f in fams):
        return False
    if not any(f in PURPLE_FAMILIES for f in fams):
        return False
    return len({HUE_GROUP[f] for f in fams}) >= 2


# --------------------------------------------------------------------------
# Lengths and Tailwind classes
# --------------------------------------------------------------------------

def px(value):
    """CSS length to px (rem/em at 16 px). None for percentages and unknowns."""
    if value is None:
        return None
    m = re.match(r"\s*(-?[\d.]+)\s*(px|rem|em)?\s*$", str(value))
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or "px"
    return n * 16.0 if unit in ("rem", "em") else n


def first_radius_px(value):
    if not value:
        return None
    first = value.split()[0]
    if first.endswith("%"):
        return 9999.0 if float(first[:-1] or 0) >= 50 else None
    return px(first)


def strip_variant(cls: str) -> str:
    depth, cut = 0, -1
    for i, ch in enumerate(cls):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == ":" and depth == 0:
            cut = i
    base = cls[cut + 1:]
    return base.lstrip("!")


TW_COLOR_RE = re.compile(
    r"^(bg|text|border|ring|from|via|to|fill|stroke|shadow|outline|decoration|divide|accent)-("
    + "|".join(TW_FAMILIES + ["white", "black"])
    + r")(?:-(\d{2,3}))?(?:/(\d{1,3}|\[[\d.]+\]))?$")
TW_ARB_COLOR_RE = re.compile(r"^(bg|text|border|ring|from|via|to|fill|stroke|shadow)-\[(.+)\]$")


def tw_color(cls: str):
    """Parse a Tailwind color utility. Returns (prefix, family_or_None, rgba, alpha)."""
    m = TW_COLOR_RE.match(cls)
    if m:
        prefix, fam, _shade, alpha = m.groups()
        a = 1.0
        if alpha:
            a = float(alpha.strip("[]")) if alpha.startswith("[") else int(alpha) / 100.0
        base = TW_500[fam]
        return prefix, fam, (base[0], base[1], base[2], a), a
    m = TW_ARB_COLOR_RE.match(cls)
    if m:
        c = parse_color(m.group(2).replace("_", " "))
        if c is not None:
            return m.group(1), None, c, c[3]
    return None


def tw_size_px(cls: str):
    """h-2 / w-1.5 / size-2 / h-[8px] to px, else None."""
    m = re.match(r"^(?:h|w|size)-(\d+(?:\.\d+)?)$", cls)
    if m:
        return float(m.group(1)) * 4.0
    m = re.match(r"^(?:h|w|size)-\[(.+)\]$", cls)
    if m:
        return px(m.group(1))
    return None


def tw_radius_px(cls: str):
    if cls in TW_RADIUS:
        return TW_RADIUS[cls]
    m = re.match(r"^rounded-\[(.+)\]$", cls)
    if m:
        return first_radius_px(m.group(1))
    return None


# --------------------------------------------------------------------------
# Markup tree
# --------------------------------------------------------------------------

class Node:
    __slots__ = ("tag", "name", "attrs", "classes", "children", "parent", "line", "_tw", "_css")

    def __init__(self, tag, name, attrs, classes, line):
        self.tag, self.name, self.attrs, self.classes, self.line = tag, name, attrs, classes, line
        self.children, self.parent = [], None
        self._tw = None
        self._css = None

    def elements(self):
        return [c for c in self.children if isinstance(c, Node)]

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()

    def text(self) -> str:
        parts = []
        for c in self.children:
            parts.append(c.text() if isinstance(c, Node) else c)
        return " ".join(" ".join(parts).split())

    def own_text(self) -> str:
        return " ".join(" ".join(c for c in self.children if isinstance(c, str)).split())

    def ancestors(self, levels):
        node, out = self.parent, []
        while node is not None and len(out) < levels:
            out.append(node)
            node = node.parent
        return out

    def tw(self) -> set:
        if self._tw is None:
            self._tw = {strip_variant(c) for c in self.classes}
        return self._tw

    def snippet(self) -> str:
        cls = " ".join(self.classes)
        return f"<{self.name}" + (f' class="{cls}"' if cls else "") + ">"


@dataclass
class CssRule:
    selector: str
    decls: dict
    line: int


@dataclass
class WebDoc:
    path: Path
    text: str
    root: Node
    css: list = field(default_factory=list)
    classmap: dict = field(default_factory=dict)
    inline: list = field(default_factory=list)   # CssRule objects built from style=""
    is_markup: bool = True

    def nodes(self):
        return [n for n in self.root.iter() if n is not self.root]


def _literals(expr: str) -> list:
    out = []
    for m in re.finditer(r"\"([^\"]*)\"|'([^']*)'|`([^`]*)`", expr):
        s = next(g for g in m.groups() if g is not None)
        out.append(re.sub(r"\$\{[^}]*\}", " ", s))
    return out


def _match_brace(src: str, start: int) -> int:
    """Index just past the brace that closes the one before `start`."""
    depth, j = 1, start
    while j < len(src) and depth:
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return j


def _camel_to_kebab(name: str) -> str:
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), name)


def _flatten_jsx(src: str) -> str:
    """Turn className={...} and style={{...}} into quoted attributes while
    keeping the line count unchanged."""
    out, i = [], 0
    pattern = re.compile(r"\b(className|class|style)=\{")
    while True:
        m = pattern.search(src, i)
        if not m:
            out.append(src[i:])
            break
        end = _match_brace(src, m.end())
        expr = src[m.end():end - 1]
        newlines = "\n" * expr.count("\n")
        out.append(src[i:m.start()])
        if m.group(1) == "style":
            decls = []
            for km in re.finditer(r"(\w+)\s*:\s*(?:'([^']*)'|\"([^\"]*)\"|`([^`]*)`|([\d.]+))",
                                  expr):
                key = _camel_to_kebab(km.group(1))
                val = next(g for g in km.groups()[1:] if g is not None)
                if km.group(5) is not None and key not in ("opacity", "z-index", "font-weight",
                                                         "flex", "line-height"):
                    val += "px"
                decls.append(f"{key}: {val}")
            out.append('style="' + "; ".join(decls).replace('"', "'") + newlines + '"')
        else:
            joined = " ".join(_literals(expr)).replace('"', " ")
            out.append('class="' + joined + newlines + '"')
        i = end
    return "".join(out)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", "#root", {}, [], 1)
        self.stack = [self.root]
        self.styles = []

    def _classes(self, attrs):
        classes = []
        for name, value in attrs:
            value = value or ""
            if name in ("class", "classname"):
                classes.extend(value.split())
            elif name in (":class", "v-bind:class", "class:list", "[class]", "[ngclass]"):
                for lit in _literals(value):
                    classes.extend(lit.split())
            elif name.startswith("class:"):
                classes.append(name[6:])
        return classes

    def _open(self, tag, attrs, selfclosing):
        line = self.getpos()[0]
        raw = self.get_starttag_text() or ""
        m = re.match(r"<\s*([A-Za-z][\w.:-]*)", raw)
        name = m.group(1) if m else tag
        attr_map = {k: (v or "") for k, v in attrs}
        node = Node(tag, name, attr_map, self._classes(attrs), line)
        parent = self.stack[-1]
        node.parent = parent
        parent.children.append(node)
        if not selfclosing and tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        top = self.stack[-1]
        if top.tag == "style":
            self.styles.append((data, self.getpos()[0]))
            return
        if top.tag == "script":
            return
        if data.strip():
            top.children.append(data)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), css, flags=re.S)


def parse_decls(body: str) -> dict:
    decls = {}
    for part in body.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip().lower()
            if k:
                decls[k] = v.strip()
    return decls


def parse_css(text: str, base_line: int = 1) -> list:
    text = _strip_comments(text)
    rules = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        sel = " ".join(m.group(1).split())
        lead = len(m.group(1)) - len(m.group(1).lstrip())
        line = base_line + text.count("\n", 0, m.start(1) + lead)
        rules.append(CssRule(sel, parse_decls(m.group(2)), line))
    return rules


def _classmap(rules) -> dict:
    cmap = {}
    for r in rules:
        for sel in r.selector.split(","):
            last = re.split(r"[\s>+~]+", sel.strip())[-1] if sel.strip() else ""
            pseudo = "before" if ":before" in last else "after" if ":after" in last else None
            if re.search(r":(hover|focus|active|visited|disabled)", last):
                continue
            for cls in re.findall(r"\.([\w-]+)", last):
                cmap.setdefault(cls, []).append((pseudo, r))
    return cmap


def parse_web(text: str, path: Path | None = None) -> WebDoc:
    path = path or Path("inline.html")
    is_css = path.suffix.lower() in (".css", ".scss")
    if is_css:
        rules = parse_css(text)
        return WebDoc(path, text, Node("#root", "#root", {}, [], 1), rules, _classmap(rules), [],
                      is_markup=False)
    builder = _TreeBuilder()
    src = _flatten_jsx(text) if path.suffix.lower() in (".jsx", ".tsx", ".js", ".ts", ".astro",
                                                          ".svelte", ".vue") else text
    try:
        builder.feed(src)
        builder.close()
    except Exception:
        pass  # html.parser is tolerant; a hard failure leaves a partial tree
    rules = []
    for css, line in builder.styles:
        rules.extend(parse_css(css, base_line=line))
    inline = []
    for node in builder.root.iter():
        style = node.attrs.get("style") if node is not builder.root else None
        if style:
            node._css = parse_decls(style)
            inline.append(CssRule(f"[style]@{node.name}", node._css, node.line))
    return WebDoc(path, text, builder.root, rules, _classmap(rules), inline, is_markup=True)


def load(path: Path) -> WebDoc:
    return parse_web(read_text(path), path)


def sniff(path: Path, head: bytes) -> int:
    name = path.name.lower()
    if name.endswith(".blade.php"):
        return 80
    ext = path.suffix.lower()
    if ext in (".html", ".htm", ".vue", ".svelte", ".astro", ".css", ".scss"):
        return 80
    if ext in (".jsx", ".tsx"):
        return 80
    if ext in (".js", ".ts") and b"className=" in head:
        return 40
    if ext == ".php" and re.search(rb"<(div|section|html|body)\b", head):
        return 40
    return 0


register_domain(DOMAIN, load=load, sniff=sniff, extensions=EXTENSIONS,
                description="HTML/JSX/Vue/Svelte/Blade markup, Tailwind classes and CSS")


# --------------------------------------------------------------------------
# Style access helpers
# --------------------------------------------------------------------------

def node_decls(doc: WebDoc, node: Node, pseudo=None) -> dict:
    merged = {}
    for cls in node.classes:
        for ps, r in doc.classmap.get(cls, ()):
            if ps == pseudo:
                merged.update(r.decls)
    if pseudo is None and node._css:
        merged.update(node._css)
    return merged


def all_css_rules(doc: WebDoc) -> list:
    return list(doc.css) + list(doc.inline)


def gradient_families(tw: set):
    fams = {"from": None, "via": None, "to": None}
    colors = []
    for c in tw:
        parsed = tw_color(c)
        if parsed and parsed[0] in fams:
            fams[parsed[0]] = parsed[1]
            colors.append((parsed[0], parsed[2]))
    order = {"from": 0, "via": 1, "to": 2}
    colors.sort(key=lambda pc: order[pc[0]])
    return fams, [c for _, c in colors]


def has_tw_gradient(tw: set) -> bool:
    return any(re.match(r"^bg-(gradient-to|linear-to|radial|conic|linear-\d+|linear-\[)", c)
               for c in tw) or any(c.startswith(("from-", "to-")) for c in tw)


def css_gradient_colors(decls: dict) -> list:
    for key in ("background", "background-image"):
        v = decls.get(key, "")
        if "gradient(" in v:
            return colors_in(v.split("gradient(", 1)[1])
    return []


def text_clipped(tw: set, decls: dict) -> bool:
    if "bg-clip-text" in tw:
        return True
    return "text" in decls.get("background-clip", "") or \
        "text" in decls.get("-webkit-background-clip", "")


def shadow_layers(value: str) -> list:
    """Split a box-shadow value into (offset_x, offset_y, blur, color, inset)."""
    layers = []
    for part in re.split(r",(?![^(]*\))", value or ""):
        part = part.strip()
        if not part or part == "none":
            continue
        cols = colors_in(part)
        stripped = COLOR_TOKEN_RE.sub(lambda m: m.group(0) if px(m.group(0)) is not None
                                      else " ", part)
        nums = [px(t) for t in stripped.split() if px(t) is not None]
        nums += [0.0] * (3 - len(nums)) if len(nums) < 3 else []
        layers.append((nums[0], nums[1], nums[2], cols[0] if cols else None,
                       "inset" in part))
    return layers


def is_glow(layer) -> bool:
    ox, oy, blur, color, inset = layer
    if inset or color is None:
        return False
    if abs(ox) > 1 or abs(oy) > 1 or blur < GLOW_MIN_BLUR_PX:
        return False
    h, s, l = hsl(color)
    return s >= 0.45 and 0.2 <= l <= 0.85 and (len(color) < 4 or color[3] >= 0.25)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def _outline_group(doc, node):
    tw = node.tw()
    has_border = any(re.match(r"^(border|border-[1248]|border-\[\d+px\]|ring|ring-1|ring-2|"
                              r"ring-inset)$", c) for c in tw)
    if has_border:
        for c in tw:
            parsed = tw_color(c)
            if parsed and parsed[0] in ("border", "ring"):
                return HUE_GROUP.get(parsed[1]) if parsed[1] else hue_group(parsed[2])
    d = node_decls(doc, node)
    for key in ("border", "border-color", "outline", "box-shadow"):
        cols = colors_in(d.get(key, ""))
        if cols:
            return hue_group(cols[0])
    return None


def _is_pill(doc, node) -> bool:
    if "rounded-full" in node.tw():
        return True
    if any((tw_radius_px(c) or 0) >= PILL_RADIUS_PX for c in node.tw()):
        return True
    r = first_radius_px(node_decls(doc, node).get("border-radius"))
    return r is not None and r >= PILL_RADIUS_PX


def _dot_group(doc, node):
    tw = node.tw()
    sizes = [s for s in (tw_size_px(c) for c in tw) if s is not None]
    round_ = "rounded-full" in tw
    if round_ and sizes and max(sizes) <= DOT_MAX_PX:
        for c in tw:
            parsed = tw_color(c)
            if parsed and parsed[0] in ("bg", "fill", "text"):
                return HUE_GROUP.get(parsed[1]) if parsed[1] else hue_group(parsed[2])
    if node.tag == "svg" and sizes and max(sizes) <= DOT_MAX_PX:
        for c in tw:
            parsed = tw_color(c)
            if parsed and parsed[0] in ("fill", "text"):
                return HUE_GROUP.get(parsed[1]) if parsed[1] else hue_group(parsed[2])
    d = node_decls(doc, node)
    return _css_dot_group(d)


def _css_dot_group(d: dict):
    r = first_radius_px(d.get("border-radius"))
    w = px(d.get("width"))
    if r is not None and r >= 3 and w is not None and w <= DOT_MAX_PX:
        cols = colors_in(d.get("background", "") + " " + d.get("background-color", ""))
        if cols:
            return hue_group(cols[0])
    return None


def pill_dot_badges(doc: WebDoc):
    """Yield (node, group) for pills holding a dot whose hue equals the outline."""
    for node in doc.nodes():
        if not _is_pill(doc, node):
            continue
        outline = _outline_group(doc, node)
        if not outline:   # neutral pills count too: recoloring to gray is not a fix
            continue
        dots = []
        for child in node.elements():
            dots.append(child)
            dots.extend(child.elements())
        groups = [_dot_group(doc, d) for d in dots]
        groups.append(_css_dot_group(node_decls(doc, node, "before")))
        if outline in groups:
            yield node, outline


@rule("web.pill-dot-outline-badge", recognition="web-pill-dot-outline-badge", severity=4)
def r_pill_dot(doc: WebDoc):
    """Pill badge with an inner dot whose color matches the outline."""
    for node, group in pill_dot_badges(doc):
        yield hit(f"line {node.line}", f"{group} pill + dot + outline: {node.snippet()} "
                  f"{node.text()[:30]}", 0.9)


def purple_gradients(doc: WebDoc):
    for node in doc.nodes():
        tw = node.tw()
        if not has_tw_gradient(tw) or text_clipped(tw, {}):
            continue
        fams, cols = gradient_families(tw)
        named = [fams["from"], fams["via"], fams["to"]]
        if all(named[i] for i in (0, 2)) and is_purple_blue_families(named):
            yield node.line, f"{fams['from']} -> {fams['to']}: {node.snippet()}"
        elif cols and is_purple_blue_gradient(cols):
            yield node.line, f"arbitrary purple/blue stops: {node.snippet()}"
    for r in all_css_rules(doc):
        if text_clipped(set(), r.decls):
            continue
        cols = css_gradient_colors(r.decls)
        if cols and is_purple_blue_gradient(cols):
            v = r.decls.get("background") or r.decls.get("background-image")
            yield r.line, f"{r.selector} {{ background: {v} }}"


@rule("web.purple-blue-gradient", recognition="web-purple-blue-gradient-hero", severity=4)
def r_purple_gradient(doc: WebDoc):
    """Purple/indigo/violet to blue gradient used as a background."""
    for line, ev in purple_gradients(doc):
        yield hit(f"line {line}", ev, 0.85)


@rule("web.gradient-text", recognition="web-gradient-clipped-headline", severity=4)
def r_gradient_text(doc: WebDoc):
    """Text filled with a gradient through background-clip: text."""
    for node in doc.nodes():
        tw = node.tw()
        if "bg-clip-text" in tw and "text-transparent" in tw and has_tw_gradient(tw):
            yield hit(f"line {node.line}", f"{node.snippet()} {node.text()[:40]}", 0.95)
    for r in all_css_rules(doc):
        d = r.decls
        transparent = "transparent" in d.get("color", "") or \
            "transparent" in d.get("-webkit-text-fill-color", "")
        bg = d.get("background", "") + d.get("background-image", "")
        if text_clipped(set(), d) and transparent and "gradient(" in bg:
            yield hit(f"line {r.line}", f"{r.selector}: background-clip text + gradient", 0.95)


def _is_cta(node: Node) -> bool:
    if node.tag == "button" or node.attrs.get("role") == "button":
        return True
    if node.tag != "a":
        return False
    tw = node.tw()
    cls = " ".join(node.classes).lower()
    return "btn" in cls or "button" in cls or (
        any(c.startswith(("bg-", "border")) for c in tw) and any(c.startswith(("px-", "py-",
                                                                               "rounded"))
                                                                for c in tw))


def _headline_nodes(doc):
    for node in doc.nodes():
        if node.tag == "h1":
            yield node
        elif any(re.match(r"^text-([5-9]xl)$", c) for c in node.tw()) and node.tag not in \
                HEADING_TAGS:
            yield node


@rule("web.vague-hero-verb", recognition="web-vague-verb-hero", severity=4)
def r_vague_hero(doc: WebDoc):
    """Hero headline built on a vague power verb (Supercharge, Elevate, Unlock)."""
    for node in _headline_nodes(doc):
        text = node.text()
        m = HERO_VERB_RE.search(text)
        if not m:
            continue
        ctas = 0
        for anc in node.ancestors(SECTION_LEVELS):
            ctas = max(ctas, sum(1 for n in anc.iter() if _is_cta(n)))
        conf = 0.9 if ctas >= 2 else 0.7
        yield hit(f"line {node.line}", f"'{m.group(0)}' in headline: {text[:70]} "
                  f"({ctas} CTA)", conf)


def _shape(node: Node, depth: int = 0):
    """Structural fingerprint; any icon (svg, i, img, PascalCase component) is one token."""
    if node.tag in ("svg", "i", "img") or node.name[:1].isupper():
        return ("icon",)
    if depth > 4:
        return (node.tag,)
    return (node.tag,) + tuple(_shape(c, depth + 1) for c in node.elements())


def _is_icon_tile(doc, node: Node) -> bool:
    tw = node.tw()
    tinted = False
    for c in tw:
        parsed = tw_color(c)
        if parsed and parsed[0] == "bg" and (parsed[1] not in NEUTRAL_FAMILIES or parsed[1] is None):
            tinted = True
    rounded = any(c.startswith("rounded") for c in tw)
    sizes_w = [tw_size_px(c) for c in tw if c.startswith(("w-", "size-"))]
    sizes_h = [tw_size_px(c) for c in tw if c.startswith(("h-", "size-"))]
    square = bool(sizes_w and sizes_h and sizes_w[0] == sizes_h[0] and sizes_w[0] and
                  sizes_w[0] <= ICON_TILE_MAX_PX)
    if not (tinted and rounded and square):
        d = node_decls(doc, node)
        w, h = px(d.get("width")), px(d.get("height"))
        bg = colors_in(d.get("background", "") + " " + d.get("background-color", ""))
        if not (w and h and w == h and w <= ICON_TILE_MAX_PX and bg and
                d.get("border-radius")):
            return False
    for d in node.iter():
        if d is node:
            continue
        if d.tag in ("svg", "i", "img") or "icon" in d.name.lower() or \
                d.name[:1].isupper():
            return True
    return any(ord(ch) > 0x2000 for ch in node.text())


def _card_has_parts(doc, card: Node) -> bool:
    has_tile = any(_is_icon_tile(doc, d) for d in card.iter() if d is not card)
    has_head = any(d.tag in HEADING_TAGS or "font-semibold" in d.tw() or "font-bold" in d.tw()
                   for d in card.iter())
    has_body = any(d.tag == "p" for d in card.iter())
    return has_tile and has_head and has_body


@rule("web.three-icon-cards", recognition="web-three-icon-feature-cards", severity=4)
def r_three_cards(doc: WebDoc):
    """Row of identical feature cards, each led by an icon in a tinted rounded square."""
    for node in doc.nodes():
        kids = node.elements()
        if len(kids) < CARD_ROW_MIN:
            continue
        groups = {}
        for k in kids:
            groups.setdefault(_shape(k), []).append(k)
        for shape, members in groups.items():
            if len(members) >= CARD_ROW_MIN and len(shape) > 1 and \
                    all(_card_has_parts(doc, m) for m in members):
                titles = [next((d.text() for d in m.iter() if d.tag in HEADING_TAGS), "")
                          for m in members]
                yield hit(f"line {node.line}", f"{len(members)} identical icon cards: "
                          + " | ".join(t[:20] for t in titles), 0.9)
                break


def _glass_tw(tw: set) -> bool:
    if not any(c.startswith("backdrop-blur") for c in tw):
        return False
    translucent = False
    for c in tw:
        parsed = tw_color(c)
        if parsed and parsed[0] == "bg" and parsed[1] == "white" and \
                GLASS_ALPHA_RANGE[0] <= parsed[3] <= GLASS_ALPHA_RANGE[1]:
            translucent = True
    edge = any((tw_color(c) or ("", ""))[0:2] in (("border", "white"), ("ring", "white"))
               for c in tw)
    return translucent and edge


def _glass_css(d: dict) -> bool:
    blur = "blur(" in d.get("backdrop-filter", "") or "blur(" in d.get("-webkit-backdrop-filter",
                                                                       "")
    if not blur:
        return False
    bg = colors_in(d.get("background", "") + " " + d.get("background-color", ""))
    translucent = any(c[0] > 240 and c[1] > 240 and c[2] > 240 and
                      GLASS_ALPHA_RANGE[0] <= c[3] <= GLASS_ALPHA_RANGE[1] for c in bg)
    border = colors_in(d.get("border", "") + " " + d.get("border-color", ""))
    edge = any(c[0] > 240 and c[1] > 240 and c[2] > 240 for c in border)
    return translucent and edge


def glass_hits(doc: WebDoc):
    for node in doc.nodes():
        if _glass_tw(node.tw()):
            yield node.line, node.snippet()
    for r in all_css_rules(doc):
        if _glass_css(r.decls):
            yield r.line, f"{r.selector}: backdrop blur + white/alpha + white border"


@rule("web.glassmorphism", recognition="web-glassmorphism-card", severity=3)
def r_glass(doc: WebDoc):
    """Backdrop blur + translucent white fill + thin white border."""
    for line, ev in glass_hits(doc):
        yield hit(f"line {line}", ev, 0.9)


def _heavy_tw(tw: set):
    radius = max((tw_radius_px(c) or 0 for c in tw), default=0)
    shadow = max((TW_SHADOW_BLUR.get(c, 0) for c in tw), default=0)
    for c in tw:
        m = re.match(r"^shadow-\[(.+)\]$", c)
        if m:
            layers = shadow_layers(m.group(1).replace("_", " "))
            shadow = max([shadow] + [l[2] for l in layers])
    return HEAVY_RADIUS_PX <= radius < 9999 and shadow >= HEAVY_SHADOW_BLUR_PX


def _heavy_css(d: dict) -> bool:
    r = first_radius_px(d.get("border-radius"))
    layers = shadow_layers(d.get("box-shadow", ""))
    blur = max((l[2] for l in layers if not l[4]), default=0)
    return r is not None and HEAVY_RADIUS_PX <= r < 9999 and blur >= HEAVY_SHADOW_BLUR_PX


@rule("web.rounded-shadow-ratio", recognition="web-rounded-shadow-everywhere", severity=3)
def r_rounded_shadow(doc: WebDoc):
    """Most containers carry rounded-2xl+ and shadow-xl+ at the same time."""
    containers, heavy = 0, []
    for node in doc.nodes():
        tw = node.tw()
        if node.tag not in CONTAINER_TAGS:
            continue
        styled = any(c.startswith(("bg-", "border", "p-", "px-", "py-", "rounded", "shadow"))
                     for c in tw)
        if not styled:
            continue
        containers += 1
        if _heavy_tw(tw):
            heavy.append(node.line)
    for r in doc.css:
        d = r.decls
        if "border-radius" in d or "box-shadow" in d:
            containers += 1
            if _heavy_css(d):
                heavy.append(r.line)
    if len(heavy) >= HEAVY_MIN_COUNT and containers and len(heavy) / containers >= HEAVY_MIN_RATIO:
        yield hit(f"line {heavy[0]}", f"{len(heavy)} of {containers} containers are "
                  f"rounded>={HEAVY_RADIUS_PX}px with shadow blur>={HEAVY_SHADOW_BLUR_PX}px", 0.85)


FONT_SHORTHAND_PREFIX = re.compile(
    r"^((normal|italic|oblique|bold|bolder|lighter|small-caps|\d{3}|"
    r"[\d.]+(px|rem|em|%|pt)?(/[\d.]+(px|rem|em|%)?)?)\s+)+", re.I)

GENERIC_SANS = {"inter", "system-ui", "-apple-system", "blinkmacsystemfont", "segoe ui", "roboto",
                "helvetica", "helvetica neue", "arial", "sans-serif", "ui-sans-serif", "sans",
                "geist", "geist sans", "poppins", "inter var", "inter variable"}


def font_evidence(doc: WebDoc):
    """Return (families_with_lines, contrast_count, size_levels)."""
    fams = []
    for r in all_css_rules(doc):
        for key in ("font-family", "font"):
            v = r.decls.get(key)
            if not v:
                continue
            if key == "font":
                v = FONT_SHORTHAND_PREFIX.sub("", v)
            first = v.split(",")[0].strip().strip("'\"").lower()
            if first and first not in ("inherit", "initial", "unset", "var(--font-sans)"):
                fams.append((first, r.line))
    for m in re.finditer(r"fonts\.googleapis\.com/css2?\?([^\"'>\s]+)", doc.text):
        for fam in re.findall(r"family=([^&:;]+)", m.group(1)):
            fams.append((fam.replace("+", " ").lower(), line_of(doc.text, m.start())))
    for m in re.finditer(r"fontFamily\s*:\s*\{[^}]*?sans\s*:\s*\[\s*['\"]([^'\"]+)", doc.text):
        fams.append((m.group(1).lower(), line_of(doc.text, m.start())))
    contrast = 0
    sizes = set()
    for node in doc.nodes():
        tw = node.tw()
        for c in tw:
            if c == "font-sans":
                fams.append(("sans", node.line))
            elif c in ("font-serif", "font-mono"):
                fams.append((c[5:], node.line))
            elif re.match(r"^font-\[(.+)\]$", c):
                fams.append((c[6:-1].replace("_", " ").strip("'\"").lower(), node.line))
            if c in ("uppercase", "small-caps", "italic") or c.startswith("font-display"):
                contrast += 1
            m = re.match(r"^text-(xs|sm|base|lg|xl|[2-9]xl)$", c)
            if m:
                sizes.add(m.group(1))
        if node.tag in HEADING_TAGS:
            sizes.add(node.tag)
    for r in all_css_rules(doc):
        d = r.decls
        if "uppercase" in d.get("text-transform", "") or "italic" in d.get("font-style", "") or \
                "small-caps" in d.get("font-variant", ""):
            contrast += 1
        if "font-size" in d:
            sizes.add(d["font-size"])
    return fams, contrast, sizes


@rule("web.single-sans-font", recognition="web-single-sans-no-hierarchy", severity=3)
def r_single_sans(doc: WebDoc):
    """One generic sans family for everything; hierarchy only by size."""
    fams, contrast, sizes = font_evidence(doc)
    if not fams:
        return
    names = {f for f, _ in fams}
    if not names <= GENERIC_SANS:
        return
    if contrast == 0 and len(sizes) >= 2:
        yield hit(f"line {fams[0][1]}", f"only {', '.join(sorted(names))}; {len(sizes)} size "
                  "steps, no second family, no case or style contrast", 0.75)


def _logo_like(node: Node) -> bool:
    if node.tag == "img":
        return True
    if node.tag == "svg" and node.parent is not None and node.parent.tag != "button":
        return True
    t = node.own_text()
    return bool(t) and bool(PLACEHOLDER_BRANDS.match(t))


@rule("web.trusted-by-strip", recognition="web-trusted-by-logo-strip", severity=3)
def r_trusted_by(doc: WebDoc):
    """'Trusted by' line followed by a strip of logos or placeholder brands."""
    seen = set()
    for node in doc.nodes():
        own = node.own_text()
        m = TRUST_RE.search(own)
        if not m:
            continue
        for anc in node.ancestors(SECTION_LEVELS):
            logos = [n for n in anc.iter() if n is not node and _logo_like(n)]
            if len(logos) >= LOGO_STRIP_MIN and anc.line not in seen:
                seen.add(anc.line)
                placeholders = sum(1 for n in logos if PLACEHOLDER_BRANDS.match(n.own_text() or
                                                                                 "-"))
                conf = 0.9 if placeholders else 0.75
                yield hit(f"line {node.line}", f"'{m.group(0)}' + {len(logos)} logos"
                          + (f" ({placeholders} placeholder names)" if placeholders else ""),
                          conf)
                break


def sparkle_hits(text: str):
    """Yield (line, token, confidence) for sparkle glyphs standing in for AI."""
    lines = set()
    for pat in SPARKLE_PATTERNS:
        for m in pat.finditer(text):
            ln = line_of(text, m.start())
            if ln in lines:
                continue
            lines.add(ln)
            window = text[max(0, m.start() - 200): m.end() + 200]
            conf = 0.9 if AI_WORD_RE.search(window) else 0.7
            token = m.group(0) if m.group(0).isascii() else "U+2728 sparkles emoji"
            yield ln, token, conf


@rule("web.sparkles-ai-icon", recognition="web-sparkles-ai-icon", severity=3)
def r_sparkles(doc: WebDoc):
    """Sparkles glyph used as the symbol for AI features."""
    for ln, token, conf in sparkle_hits(doc.text):
        yield hit(f"line {ln}", token, conf)


def _dark_evidence(doc: WebDoc) -> bool:
    for node in doc.nodes():
        for c in node.tw():
            if re.match(r"^bg-(black|(slate|gray|zinc|neutral|stone)-(9\d\d))", c):
                return True
    for r in all_css_rules(doc):
        for c in colors_in(r.decls.get("background", "") + " " +
                           r.decls.get("background-color", "")):
            if hsl(c)[2] < 0.15:
                return True
    return False


def neon_glows(doc: WebDoc) -> list:
    """(line, evidence) for every colored zero-offset glow in the document."""
    glows = []
    for node in doc.nodes():
        for c in node.tw():
            m = re.match(r"^(?:shadow|drop-shadow)-\[(.+)\]$", c)
            if m and any(is_glow(l) for l in shadow_layers(m.group(1).replace("_", " "))):
                glows.append((node.line, c))
            parsed = tw_color(c)
            if parsed and parsed[0] == "shadow" and parsed[1] and                     parsed[1] not in NEUTRAL_FAMILIES:
                glows.append((node.line, c))
    for r in all_css_rules(doc):
        for key in ("box-shadow", "text-shadow"):
            if any(is_glow(l) for l in shadow_layers(r.decls.get(key, ""))):
                glows.append((r.line, f"{r.selector} {key}"))
        f = r.decls.get("filter", "")
        if "drop-shadow(" in f and any(is_glow(l) for l in
                                       shadow_layers(f.split("drop-shadow(", 1)[1].rstrip(")"))):
            glows.append((r.line, f"{r.selector} drop-shadow"))
    return glows


@rule("web.neon-glow", recognition="web-neon-glow-dark", severity=3)
def r_neon_glow(doc: WebDoc):
    """Colored zero-offset glow shadows on several cards or buttons."""
    glows = neon_glows(doc)
    if len(glows) >= GLOW_MIN_COUNT:
        conf = 0.85 if _dark_evidence(doc) else 0.65
        for line, ev in glows[:10]:
            yield hit(f"line {line}", f"colored glow {ev}", conf)


SPAN_RE = re.compile(r"^(col|row)-span-(\d+|full)$")


@rule("web.default-bento", recognition="web-default-bento-grid", severity=3)
def r_bento(doc: WebDoc):
    """Template bento grid: identical tiles, sizes set only by span classes."""
    for node in doc.nodes():
        tw = node.tw()
        cols = [int(m.group(1)) for m in (re.match(r"^grid-cols-(\d+)$", c) for c in tw) if m]
        css_cols = re.match(r"repeat\(\s*(\d+)", node_decls(doc, node).get(
            "grid-template-columns", ""))
        ncols = max(cols + ([int(css_cols.group(1))] if css_cols else []), default=0)
        if ncols < 3 or not ("grid" in tw or node_decls(doc, node).get("display") == "grid"):
            continue
        kids = node.elements()
        if len(kids) < BENTO_MIN_TILES:
            continue
        spans, bases = 0, set()
        for k in kids:
            ktw = k.tw()
            kd = node_decls(doc, k)
            if any(SPAN_RE.match(c) for c in ktw) or "span" in kd.get("grid-column", "") or \
                    "span" in kd.get("grid-row", ""):
                spans += 1
            bases.add((k.tag, frozenset(c for c in ktw if not SPAN_RE.match(c) and
                                        not re.match(r"^(bg|from|via|to)-", c))))
        if spans >= 1 and len(bases) == 1:
            fixed_rows = any(c.startswith(("auto-rows-", "grid-rows-")) for c in tw)
            yield hit(f"line {node.line}", f"{len(kids)} identical tiles in grid-cols-{ncols}, "
                      f"{spans} sized only by span classes" + (", fixed row height"
                                                               if fixed_rows else ""),
                      0.85 if fixed_rows else 0.7)
