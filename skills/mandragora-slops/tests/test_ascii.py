"""ASCII renderer tests: printable ASCII, width limits, determinism."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))

from scanners import ascii_render as A  # noqa: E402

FIX = HERE / "fixtures"
SAMPLES = [
    ("web", FIX / "web" / "slop" / "web-three-icon-feature-cards.jsx"),
    ("web", FIX / "web" / "clean" / "web-vague-verb-hero.html"),
    ("web", FIX / "web" / "slop" / "web-trusted-by-logo-strip.vue"),
    ("app", FIX / "app" / "clean" / "app-purple-gradient-header.xaml"),
    ("app", FIX / "app" / "slop" / "app-pill-dot-status-chip.swift"),
    ("app", FIX / "app" / "slop" / "app-identical-tile-grid.kt"),
    ("tui", FIX / "tui" / "slop" / "tui-emoji-title-box-frames.ansi"),
    ("tui", FIX / "tui" / "slop" / "tui-rainbow-ansi.ansi"),
    ("texture", FIX / "texture" / "clean" / "texture-mirror-symmetry.png"),
    ("texture", FIX / "texture" / "slop" / "texture-flat-roughness.png"),
    ("model3d", FIX / "model3d" / "slop" / "model3d-uniform-bevel-width.obj"),
    ("model3d", FIX / "model3d" / "clean" / "model3d-uv-stretch.gltf"),
    ("copy", FIX / "copy" / "slop" / "copy-emoji-bullets.md"),
    ("copy", FIX / "copy" / "clean" / "copy-dash-connector.md"),
]
WIDTHS = (A.MIN_WIDTH, 40, 80, A.MAX_WIDTH)


def assert_ascii(case: unittest.TestCase, text: str, width: int):
    case.assertTrue(text.endswith("\n"))
    for line in text.split("\n"):
        case.assertLessEqual(len(line), width, line)
        case.assertTrue(all(0x20 <= ord(ch) <= 0x7E for ch in line), repr(line))


class RendererTests(unittest.TestCase):
    def test_samples_ascii_within_width(self):
        for domain, path in SAMPLES:
            for width in WIDTHS:
                with self.subTest(file=path.name, width=width):
                    out = A.render_path(path, domain, width)
                    assert_ascii(self, out, width)
                    self.assertTrue(out.strip())

    def test_deterministic(self):
        for domain, path in SAMPLES:
            with self.subTest(file=path.name):
                self.assertEqual(A.render_path(path, domain, 72), A.render_path(path, domain, 72))

    def test_width_is_clamped(self):
        out = A.render_path(FIX / "web" / "clean" / "web-vague-verb-hero.html", "web", 400)
        assert_ascii(self, out, A.MAX_WIDTH)

    def test_layout_spec(self):
        spec = {"type": "box", "title": "Billing", "children": [
            {"type": "heading", "text": "Invoices"},
            {"type": "row", "children": [{"type": "text", "text": "Invoice 1042"},
                                         {"type": "button", "text": "Pay"}]},
            {"type": "input", "text": "Search"}, {"type": "image", "text": "chart"},
            {"type": "rule"}]}
        out = A.render_layout(spec, 50)
        assert_ascii(self, out, 50)
        self.assertIn("[ Pay ]", out)
        self.assertIn("Billing", out.splitlines()[0])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "layout.json"
            p.write_text(json.dumps(spec), encoding="utf-8")
            self.assertEqual(A.render_path(p, None, 50), out)

    def test_texture_uses_ramp_only(self):
        out = A.render_path(FIX / "texture" / "clean" / "texture-mirror-symmetry.png", "texture", 48)
        self.assertTrue(set(out) <= set(A.RAMP) | {"\n"})

    def test_mesh_views(self):
        out = A.render_path(FIX / "model3d" / "slop" / "model3d-floating-parts.obj", "model3d", 90)
        first = out.splitlines()[0]
        for view in ("front", "side", "top"):
            self.assertIn(view, first)
        self.assertIn("+", out)
        single = A.render_path(FIX / "model3d" / "slop" / "model3d-floating-parts.obj",
                               "model3d", 60, view="top")
        self.assertNotIn("front", single.splitlines()[0])

    def test_unicode_transliteration(self):
        self.assertEqual(A.to_ascii("✅ done — “ok”"), '[ok] done - "ok"')

    def test_cli(self):
        proc = subprocess.run([sys.executable, "-m", "scanners.ascii_render",
                               str(FIX / "tui" / "slop" / "tui-emoji-status-markers.ansi"),
                               "--width", "60"], cwd=SKILL_DIR, capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        assert_ascii(self, proc.stdout, 60)


if __name__ == "__main__":
    unittest.main()
