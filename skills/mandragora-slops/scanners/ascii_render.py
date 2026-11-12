"""ASCII renderers for every domain (used in redesign step S6).

    python -m scanners.ascii_render <path> [--domain D] [--width N] [--view front|side|top|all]

- web / app: layout boxes from HTML/JSX/Vue/Svelte, XAML, SwiftUI or Compose source,
  or from a JSON layout spec ({"type": "col", "children": [...]}) for any toolkit.
- tui: captured terminal output with ANSI removed, box drawing and emoji transliterated.
- texture: luminance sample with the ramp " .:-=+*#%@".
- model3d: orthographic wireframe (front, side, top).
- copy: prose reflowed to the width, headings underlined.

Output is printable ASCII only, never wider than --width (max 100), and
deterministic for the same input.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RAMP = " .:-=+*#%@"
DEFAULT_WIDTH = 80
MAX_WIDTH = 100            # recognition files and terminals cap at 100 columns
MIN_WIDTH = 20             # below this a layout cannot show nesting
ROW_GAP = 2                # columns between side-by-side children
IMAGE_HEIGHT = 3           # rows used by an image placeholder box
MAX_TEXTURE_ROWS = 40      # keeps texture previews on one screen
MESH_VIEW_HEIGHT = 18      # rows per orthographic view

EMOJI_NAMES = {
    0x2705: "[ok]", 0x274C: "[x]", 0x1F680: "[rocket]", 0x2728: "[sparkles]",
    0x1F389: "[party]", 0x1F4E6: "[pkg]", 0x26A0: "[!]", 0x1F525: "[fire]", 0x1F4A1: "[idea]",
    0x1F44B: "[wave]", 0x1F512: "[lock]", 0x1F4CA: "[chart]", 0x2714: "[ok]", 0x2716: "[x]",
}
CHAR_MAP = {
    "─": "-", "═": "=", "━": "-", "│": "|", "║": "|", "┃": "|",
    "█": "#", "▓": "%", "▒": ":", "░": ".", "■": "#", "□": ".",
    "▰": "#", "▱": ".", "●": "o", "○": "o", "•": "*",
    "—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", " ": " ", "↑": "^", "↓": "v", "→": "->", "←": "<-",
}


# --------------------------------------------------------------------------
# ASCII helpers
# --------------------------------------------------------------------------

def to_ascii(text: str) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        if ch == "\n" or 0x20 <= cp <= 0x7E:
            out.append(ch)
        elif ch == "\t":
            out.append("    ")
        elif ch in CHAR_MAP:
            out.append(CHAR_MAP[ch])
        elif cp in EMOJI_NAMES:
            out.append(EMOJI_NAMES[cp])
        elif 0x2500 <= cp <= 0x257F:
            out.append("+")
        elif 0x2800 <= cp <= 0x28FF:
            out.append("*")
        elif cp in (0xFE0F, 0x200D):
            continue
        elif cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF:
            out.append("[?]")
        else:
            out.append("?")
    return "".join(out)


def finish(lines, width: int) -> str:
    clean = [to_ascii(l).rstrip()[:width] for l in lines]
    while clean and not clean[-1]:
        clean.pop()
    return "\n".join(clean) + "\n"


def wrap(text: str, width: int) -> list:
    words = to_ascii(" ".join(text.split())).split(" ")
    lines, cur = [], ""
    for w in words:
        if not w:
            continue
        while len(w) > width:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(w[:width])
            w = w[width:]
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def clamp_width(width: int) -> int:
    return max(MIN_WIDTH, min(MAX_WIDTH, int(width)))


# --------------------------------------------------------------------------
# Generic layout engine
# --------------------------------------------------------------------------

def render_node(node: dict, width: int) -> list:
    """Render a layout node to lines padded to exactly `width` characters."""
    width = max(1, width)
    kind = node.get("type", "col")
    text = str(node.get("text", "") or "")
    kids = [k for k in node.get("children", []) if k]
    if kind == "text":
        lines = wrap(text, width)
    elif kind == "heading":
        lines = wrap(text, width)
        level = int(node.get("level", 1))
        lines.append(("=" if level <= 1 else "-") * min(width, max(len(l) for l in lines)))
    elif kind == "button":
        lines = [("[ " + to_ascii(text) + " ]")[:width]]
    elif kind == "input":
        label = to_ascii(text)[: max(0, width - 4)]
        lines = [("[" + label + "_" * max(0, min(width, 32) - len(label) - 2) + "]")[:width]]
    elif kind == "image":
        inner = max(1, width - 2)
        alt = ("img: " + to_ascii(text))[:inner]
        lines = ["+" + "-" * inner + "+", "|" + alt.center(inner) + "|", "+" + "-" * inner + "+"]
    elif kind == "rule":
        lines = ["-" * width]
    elif kind == "box":
        inner = max(1, width - 4)
        title = to_ascii(node.get("title", "") or "")
        top = "+" + "-" * (width - 2) + "+"
        if title and width > 8:
            label = f"- {title} "[: width - 4]
            top = "+" + label + "-" * (width - 2 - len(label)) + "+"
        body = render_node({"type": "col", "children": kids}, inner) if kids else [" " * inner]
        lines = [top] + ["| " + l.ljust(inner)[:inner] + " |" for l in body] + \
            ["+" + "-" * (width - 2) + "+"]
    elif kind == "row" and kids:
        n = len(kids)
        gap = ROW_GAP if width >= n * 6 else 1
        col_w = max(1, (width - gap * (n - 1)) // n)
        blocks = [render_node(k, col_w) for k in kids]
        height = max(len(b) for b in blocks)
        lines = []
        for i in range(height):
            parts = [(b[i] if i < len(b) else "").ljust(col_w)[:col_w] for b in blocks]
            lines.append((" " * gap).join(parts))
    else:  # col and empty row
        lines = []
        if text:
            lines += wrap(text, width)
        for k in kids:
            lines += render_node(k, width)
    return [l.ljust(width)[:width] for l in lines]


def render_layout(spec: dict, width: int = DEFAULT_WIDTH) -> str:
    width = clamp_width(width)
    return finish(render_node(spec, width), width)


# --------------------------------------------------------------------------
# Markup and declarative UI to layout nodes
# --------------------------------------------------------------------------

BOX_HINT = re.compile(r"^(border|bg-|rounded|shadow|ring)|card|panel|tile", re.I)
SKIP_TAGS = {"head", "script", "style", "meta", "link", "title", "noscript", "template-skip"}
TEXT_TAGS = {"p", "span", "label", "small", "strong", "em", "b", "i", "dt", "dd", "figcaption",
             "blockquote", "code", "td", "th", "time", "abbr"}


def _html_children(doc, node) -> list:
    out = []
    for c in node.children:
        if isinstance(c, str):
            if c.strip():
                out.append({"type": "text", "text": c.strip()})
        else:
            n = _html_node(doc, c)
            if n:
                out.append(n)
    return out


def _html_node(doc, node):
    from scanners import scan_web as web

    tag = node.tag
    if tag in SKIP_TAGS:
        return None
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return {"type": "heading", "level": int(tag[1]), "text": node.text()}
    if tag == "button" or (tag == "a" and web._is_cta(node)):
        return {"type": "button", "text": node.text() or node.attrs.get("aria-label", "button")}
    if tag in ("input", "textarea", "select"):
        return {"type": "input", "text": node.attrs.get("placeholder") or node.attrs.get("name", "")}
    if tag == "img":
        return {"type": "image", "text": node.attrs.get("alt", "")}
    if tag == "svg" or node.name[:1].isupper() and not node.elements():
        return {"type": "text", "text": "*"}
    if tag == "hr":
        return {"type": "rule"}
    if tag == "li":
        return {"type": "text", "text": "- " + node.text()}
    if tag == "tr":
        return {"type": "row", "children": [{"type": "text", "text": c.text()}
                                            for c in node.elements()]}
    if tag in TEXT_TAGS and not any(c.tag not in TEXT_TAGS for c in node.elements()):
        return {"type": "text", "text": node.text()} if node.text() else None
    kids = _html_children(doc, node)
    if not kids:
        return None
    tw = node.tw()
    cols = [int(m.group(1)) for m in (re.match(r"^grid-cols-(\d+)$", c) for c in tw) if m]
    horizontal = ("flex" in tw and "flex-col" not in tw) or (cols and max(cols) >= 2)
    if horizontal:
        per = max(cols) if cols else len(kids)
        rows = [{"type": "row", "children": kids[i:i + per]} for i in range(0, len(kids), per)]
        body = rows[0] if len(rows) == 1 else {"type": "col", "children": rows}
    else:
        body = {"type": "col", "children": kids}
    decls = web.node_decls(doc, node)
    boxed = any(BOX_HINT.search(c) for c in node.classes) or "border" in decls or \
        "background" in decls or "background-color" in decls
    if boxed and tag not in ("html", "body"):
        return {"type": "box", "children": [body]}
    return body


def html_to_layout(text: str, path: Path | None = None) -> dict:
    from scanners import scan_web as web

    doc = web.parse_web(text, path or Path("inline.html"))
    return {"type": "col", "children": _html_children(doc, doc.root)}


def _xaml_node(el):
    tag = el.tag.split("}")[-1]
    attrs = {k.split("}")[-1]: v for k, v in el.attrib.items()}
    kids = [n for n in (_xaml_node(c) for c in el if "." not in c.tag.split("}")[-1]) if n]
    if tag in ("TextBlock", "Label", "Run"):
        return {"type": "text", "text": attrs.get("Text") or attrs.get("Content") or
                (el.text or "").strip()}
    if tag in ("Button", "ToggleButton", "HyperlinkButton", "AppBarButton"):
        return {"type": "button", "text": attrs.get("Content") or attrs.get("Label") or "button"}
    if tag in ("TextBox", "PasswordBox", "ComboBox", "AutoSuggestBox", "NumberBox"):
        return {"type": "input", "text": attrs.get("PlaceholderText") or attrs.get("Header", "")}
    if tag in ("Image", "PersonPicture"):
        return {"type": "image", "text": attrs.get("Source", "")}
    if tag in ("Separator", "Rectangle") and not kids:
        return {"type": "rule"}
    if not kids:
        return None
    if tag == "StackPanel" and attrs.get("Orientation") == "Horizontal":
        return {"type": "row", "children": kids}
    if tag == "Grid" and any("Grid.Column" in c.attrib for c in el):
        return {"type": "row", "children": kids}
    if tag in ("Border", "Frame", "Expander", "GroupBox"):
        return {"type": "box", "children": kids}
    if tag in ("Window", "Page", "UserControl", "ContentPage"):
        return {"type": "box", "title": attrs.get("Title", ""), "children": kids}
    return {"type": "col", "children": kids}


def xaml_to_layout(text: str) -> dict:
    root = ET.fromstring(text)
    return _xaml_node(root) or {"type": "col", "children": []}


DECL_MAP = {
    "VStack": "col", "LazyVStack": "col", "Column": "col", "LazyColumn": "col", "List": "col",
    "Form": "col", "Section": "col", "ScrollView": "col", "NavigationStack": "col",
    "ZStack": "col", "Box": "col", "HStack": "row", "LazyHStack": "row", "Row": "row",
    "LazyRow": "row", "Card": "box", "Surface": "box", "GroupBox": "box",
    "ElevatedCard": "box", "OutlinedCard": "box", "LazyVGrid": "grid", "LazyHGrid": "grid",
    "LazyVerticalGrid": "grid", "LazyHorizontalGrid": "grid", "Grid": "grid",
}
BUTTONS = {"Button", "TextButton", "OutlinedButton", "FilledTonalButton", "ElevatedButton",
           "IconButton", "FloatingActionButton", "ExtendedFloatingActionButton", "Link"}
INPUTS = {"TextField", "OutlinedTextField", "SecureField", "TextEditor", "Picker", "Toggle"}
IMAGES = {"Image", "Icon", "AsyncImage", "Label"}
RULES = {"Divider", "HorizontalDivider"}
SHAPES = {"Circle": "o", "Ellipse": "o", "Capsule": "(  )", "RoundedRectangle": "[  ]",
          "Rectangle": "[  ]"}
STRING_RE = re.compile(r"\"((?:[^\"\\]|\\.)*)\"")


def _skip_string(src: str, i: int) -> int:
    quote = src[i]
    i += 1
    while i < len(src) and src[i] != quote:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def _match(src: str, i: int, open_: str, close: str) -> int:
    depth = 0
    while i < len(src):
        ch = src[i]
        if ch in "\"'":
            i = _skip_string(src, i)
            continue
        if ch == open_:
            depth += 1
        elif ch == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(src) - 1


def _decl_children(src: str) -> list:
    out, i = [], 0
    ident = re.compile(r"[A-Za-z_][\w]*")
    while i < len(src):
        ch = src[i]
        if ch in "\"'":
            i = _skip_string(src, i)
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = len(src) if j < 0 else j
            continue
        m = ident.match(src, i)
        if m and i > 0 and src[i - 1] == ".":
            # modifier such as .padding(8) or .background(...): skip its arguments
            j = m.end()
            if j < len(src) and src[j] == "(":
                j = _match(src, j, "(", ")") + 1
            i = j
            continue
        if not m or (i > 0 and (src[i - 1].isalnum() or src[i - 1] == "_")):
            i += 1
            continue
        name, j = m.group(0), m.end()
        while j < len(src) and src[j] in " \t":
            j += 1
        args, body = "", None
        if j < len(src) and src[j] == "(":
            end = _match(src, j, "(", ")")
            args, j = src[j + 1:end], end + 1
            k = j
            while k < len(src) and src[k] in " \t\n":
                k += 1
            if k < len(src) and src[k] == "{":
                end = _match(src, k, "{", "}")
                body, j = src[k + 1:end], end + 1
        elif j < len(src) and src[j] == "{":
            end = _match(src, j, "{", "}")
            body, j = src[j + 1:end], end + 1
        else:
            i = m.end()
            continue
        node = _decl_node(name, args, body)
        if node:
            out.append(node)
        i = j
    return out


def _decl_node(name: str, args: str, body):
    lit = STRING_RE.search(args)
    label = lit.group(1) if lit else ""
    kids = _decl_children(body) if body else []
    if name == "Text":
        return {"type": "text", "text": label or "text"}
    if name in BUTTONS:
        inner = next((k.get("text") for k in kids if k.get("type") == "text"), "")
        return {"type": "button", "text": label or inner or name}
    if name in INPUTS:
        return {"type": "input", "text": label}
    if name in IMAGES:
        return {"type": "image", "text": label or name}
    if name in RULES:
        return {"type": "rule"}
    if name in SHAPES:
        return {"type": "text", "text": SHAPES[name]}
    kind = DECL_MAP.get(name)
    if kind == "grid" and kids:
        m = re.search(r"Fixed\(\s*(\d+)\s*\)|count:\s*(\d+)", args)
        per = int(next(g for g in m.groups() if g)) if m else max(1, args.count("GridItem")) or 2
        per = per if per > 1 else 2
        rows = [{"type": "row", "children": kids[i:i + per]} for i in range(0, len(kids), per)]
        return {"type": "col", "children": rows}
    if kind:
        return {"type": kind, "children": kids} if kids else None
    if kids:
        return kids[0] if len(kids) == 1 else {"type": "col", "children": kids}
    literals = STRING_RE.findall(args)
    if name[:1].isupper() and literals:
        # custom component instance, such as StatCard(title = "Revenue", value = "12")
        return {"type": "box", "title": name, "children": [
            {"type": "text", "text": "  ".join(literals)}]}
    return None


def declarative_to_layout(text: str) -> dict:
    return {"type": "col", "children": _decl_children(text)}


# --------------------------------------------------------------------------
# Domain renderers
# --------------------------------------------------------------------------

def render_ui(path: Path, text: str, width: int) -> str:
    ext = path.suffix.lower()
    if ext == ".json":
        spec = json.loads(text)
    elif ext in (".xaml", ".axaml"):
        spec = xaml_to_layout(text)
    elif ext in (".swift", ".kt", ".kts"):
        spec = declarative_to_layout(text)
    else:
        spec = html_to_layout(text, path)
    return render_layout(spec, width)


def render_tui(text: str, width: int = DEFAULT_WIDTH) -> str:
    from scanners import scan_tui

    width = clamp_width(width)
    doc = scan_tui.parse_tui(text)
    return finish([l.plain for l in doc.lines], width)


def render_texture(image, width: int = 64) -> str:
    width = clamp_width(width)
    rows = list(image.rgb_rows())
    h, w = image.height, image.width
    out_w = min(width, w)
    out_h = max(1, min(MAX_TEXTURE_ROWS, round(out_w * h / w / 2)))
    lines = []
    for oy in range(out_h):
        y0, y1 = oy * h // out_h, max(oy * h // out_h + 1, (oy + 1) * h // out_h)
        line = []
        for ox in range(out_w):
            x0, x1 = ox * w // out_w, max(ox * w // out_w + 1, (ox + 1) * w // out_w)
            total = n = 0
            for y in range(y0, y1):
                for r, g, b in rows[y][x0:x1]:
                    total += 0.2126 * r + 0.7152 * g + 0.0722 * b
                    n += 1
            v = total / max(1, n) / 255.0
            line.append(RAMP[min(len(RAMP) - 1, int(v * len(RAMP)))])
        lines.append("".join(line))
    return finish(lines, width)


def _draw_line(grid, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return
    if abs(dy) * 2 <= abs(dx):
        ch = "-"
    elif abs(dx) * 2 <= abs(dy):
        ch = "|"
    else:
        ch = "/" if (dx > 0) == (dy < 0) else "\\"
    for s in range(steps + 1):
        x = round(x0 + dx * s / steps)
        y = round(y0 + dy * s / steps)
        if 0 <= y < len(grid) and 0 <= x < len(grid[0]) and grid[y][x] == " ":
            grid[y][x] = ch


def render_mesh(mesh, width: int = DEFAULT_WIDTH, view: str = "all") -> str:
    width = clamp_width(width)
    if not mesh.positions:
        return "(empty mesh)\n"
    views = {"front": (0, 1), "side": (2, 1), "top": (0, 2)}
    chosen = list(views) if view == "all" else [view]
    gap = 2
    vw = max(10, (width - gap * (len(chosen) - 1)) // len(chosen))
    vh = MESH_VIEW_HEIGHT
    edges = set()
    for f in mesh.faces:
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            edges.add((min(a, b), max(a, b)))
    panels = []
    for name in chosen:
        ax, ay = views[name]
        xs = [p[ax] for p in mesh.positions]
        ys = [p[ay] for p in mesh.positions]
        span_x = (max(xs) - min(xs)) or 1.0
        span_y = (max(ys) - min(ys)) or 1.0
        scale = min((vw - 1) / span_x, (vh - 2) * 2 / span_y)
        off_x = (vw - 1 - span_x * scale) / 2
        off_y = (vh - 2 - span_y * scale / 2) / 2

        def proj(p):
            return (round(off_x + (p[ax] - min(xs)) * scale),
                    round(vh - 2 - (off_y + (p[ay] - min(ys)) * scale / 2)))

        grid = [[" "] * vw for _ in range(vh - 1)]
        pts = [proj(p) for p in mesh.positions]
        for a, b in sorted(edges):
            _draw_line(grid, *pts[a], *pts[b])
        for x, y in pts:
            if 0 <= y < len(grid) and 0 <= x < vw:
                grid[y][x] = "+"
        panels.append([name.ljust(vw)] + ["".join(r) for r in grid])
    lines = [(" " * gap).join(p[i] for p in panels) for i in range(vh)]
    return finish(lines, width)


def render_copy(text: str, path: Path, width: int = 72) -> str:
    from scanners import scan_copy

    width = clamp_width(width)
    doc = scan_copy.parse_copy(text, path)
    lines = []
    segments, merged = list(doc.segments), []
    for seg in segments:   # table cells on one source line become one row
        if seg.kind == "cell" and merged and merged[-1].kind == "cell" and \
                merged[-1].line == seg.line:
            merged[-1] = scan_copy.Segment(seg.line, "cell", merged[-1].text + " | " + seg.text,
                                           merged[-1].raw)
        else:
            merged.append(seg)
    for seg in merged:
        if seg.kind == "cell":
            lines += wrap(seg.text, width)
        elif seg.kind == "heading":
            if lines:
                lines.append("")
            body = wrap(seg.text, width)
            lines += body + ["-" * min(width, max(len(b) for b in body))]
        elif seg.kind == "bullet":
            body = wrap(seg.text, width - 2)
            lines += ["- " + body[0]] + ["  " + b for b in body[1:]]
        else:
            lines += wrap(seg.text, width) + [""]
    return finish(lines, width)


def render_path(path, domain: str | None = None, width: int = DEFAULT_WIDTH,
                view: str = "all") -> str:
    from scanners import core

    path = Path(path)
    if domain is None:
        domain, _ = core.detect_domain(path)
        if domain is None and path.suffix.lower() == ".json":
            domain = "app"
    if domain in ("web", "app"):
        return render_ui(path, core.read_text(path), width)
    if domain == "tui":
        return render_tui(core.read_text(path), width)
    if domain == "texture":
        from scanners.png_reader import read_png

        return render_texture(read_png(path), width)
    if domain == "model3d":
        from scanners.mesh_reader import read_mesh

        return render_mesh(read_mesh(path), width, view)
    if domain == "copy":
        return render_copy(core.read_text(path), path, width)
    raise ValueError(f"no ASCII renderer for domain {domain!r}; pass --domain")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scanners.ascii_render",
                                     description="Render a design, texture or mesh as ASCII")
    parser.add_argument("path")
    parser.add_argument("--domain")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--view", default="all", choices=("all", "front", "side", "top"))
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0
    try:
        sys.stdout.write(render_path(args.path, args.domain, args.width, args.view))
    except Exception as exc:  # report, do not trace back, for agent consumption
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    from scanners import ascii_render as _ar

    sys.exit(_ar.main())
