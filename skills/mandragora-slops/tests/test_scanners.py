"""Scanner tests: every slop fixture is recognized, every clean fixture passes,
plus domain detection, CLI contract and reader edge cases."""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))

from scanners import core, recognitions  # noqa: E402
from scanners.png_reader import PngError, _chunk, decode_png, encode_png  # noqa: E402

FIXTURES = HERE / "fixtures"
CLEAN_MAX_SEVERITY = 2   # clean fixtures may only carry findings below severity 3

core.load_scanners()


def fixture_files(domain: str, kind: str) -> list:
    folder = FIXTURES / domain / kind
    return sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []


def expected_id(path: Path) -> str:
    return path.name.split(".")[0]


class FixtureTests(unittest.TestCase):
    def test_slop_fixtures_are_recognized(self):
        for domain in sorted(core.DOMAINS):
            for path in fixture_files(domain, "slop"):
                with self.subTest(fixture=f"{domain}/slop/{path.name}"):
                    res = core.scan_file(path, [domain])
                    self.assertEqual(res.errors, [])
                    ids = {f.recognition_id for f in res.findings}
                    self.assertIn(expected_id(path), ids)

    def test_clean_fixtures_have_no_severe_findings(self):
        for domain in sorted(core.DOMAINS):
            for path in fixture_files(domain, "clean"):
                with self.subTest(fixture=f"{domain}/clean/{path.name}"):
                    res = core.scan_file(path, [domain])
                    self.assertEqual(res.errors, [])
                    severe = [f"{f.rule_id} {f.location}" for f in res.findings
                              if f.severity > CLEAN_MAX_SEVERITY]
                    self.assertEqual(severe, [])

    def test_every_static_recognition_has_both_fixtures(self):
        for rec in recognitions.load_library(core.RECOGNITIONS_DIR):
            if not rec.static_rules:
                continue
            with self.subTest(recognition=rec.id):
                slop = [p for p in fixture_files(rec.domain, "slop") if expected_id(p) == rec.id]
                clean = [p for p in fixture_files(rec.domain, "clean") if expected_id(p) == rec.id]
                self.assertTrue(slop, f"missing slop fixture for {rec.id}")
                self.assertTrue(clean, f"missing clean fixture for {rec.id}")

    def test_every_fixture_names_a_recognition(self):
        ids = {r.id for r in recognitions.load_library(core.RECOGNITIONS_DIR)}
        for domain in sorted(core.DOMAINS):
            for kind in ("slop", "clean"):
                for path in fixture_files(domain, kind):
                    with self.subTest(fixture=path.name):
                        self.assertIn(expected_id(path), ids)


class DetectionTests(unittest.TestCase):
    CASES = {
        "web/slop/web-pill-dot-outline-badge.html": "web",
        "web/slop/web-glassmorphism-card.css": "web",
        "web/slop/web-gradient-clipped-headline.tsx": "web",
        "web/slop/web-trusted-by-logo-strip.vue": "web",
        "web/slop/web-neon-glow-dark.svelte": "web",
        "app/slop/app-pill-dot-status-chip.swift": "app",
        "app/slop/app-identical-tile-grid.kt": "app",
        "app/slop/app-purple-gradient-header.xaml": "app",
        "app/slop/app-uniform-corner-radius.cpp": "app",
        "app/slop/app-glass-acrylic-panel.dart": "app",
        "app/slop/app-greeting-stat-dashboard.qml": "app",
        "tui/slop/tui-rainbow-ansi.ansi": "tui",
        "texture/slop/texture-visible-tiling-seam.png": "texture",
        "model3d/slop/model3d-triangle-soup.obj": "model3d",
        "model3d/slop/model3d-uv-stretch.gltf": "model3d",
        "copy/slop/copy-hype-vocabulary.md": "copy",
        "copy/slop/copy-sycophantic-opener.txt": "copy",
    }

    def test_auto_detection(self):
        for rel, want in self.CASES.items():
            with self.subTest(path=rel):
                got, _ = core.detect_domain(FIXTURES / rel)
                self.assertEqual(got, want)

    def test_txt_with_escape_sequences_is_tui(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "capture.txt"
            p.write_bytes(b"\x1b[31merror\x1b[0m build failed\n")
            self.assertEqual(core.detect_domain(p)[0], "tui")
            q = Path(tmp) / "notes.txt"
            q.write_text("Plain prose about the release.\n", encoding="utf-8")
            self.assertEqual(core.detect_domain(q)[0], "copy")

    def test_react_native_is_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "Screen.tsx"
            p.write_text('import { View } from "react-native";\n', encoding="utf-8")
            self.assertEqual(core.detect_domain(p)[0], "app")

    def test_core_is_domain_agnostic(self):
        source = (SKILL_DIR / "scanners" / "core.py").read_text(encoding="utf-8")
        for name in core.DOMAINS:
            self.assertNotIn(f'"{name}"', source)
            self.assertNotIn(f"'{name}'", source)
            self.assertNotIn(f"scan_{name}", source)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "scanners.core", *args], cwd=SKILL_DIR,
                              capture_output=True, text=True, timeout=300)

    def test_findings_exit_1_with_json(self):
        path = FIXTURES / "web" / "slop" / "web-pill-dot-outline-badge.html"
        proc = self.run_cli("scan", str(path), "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("web-pill-dot-outline-badge", data["recognition_ids"])
        self.assertTrue(all(set(f) >= {"rule_id", "recognition_id", "domain", "severity",
                                       "location", "evidence", "confidence"}
                            for f in data["findings"]))

    def test_clean_exit_0(self):
        path = FIXTURES / "web" / "clean" / "web-pill-dot-outline-badge.html"
        self.assertEqual(self.run_cli("scan", str(path)).returncode, 0)

    def test_min_severity_filters(self):
        path = FIXTURES / "copy" / "slop" / "copy-title-case-headings.md"
        self.assertEqual(self.run_cli("scan", str(path), "--min-severity", "3").returncode, 0)
        self.assertEqual(self.run_cli("scan", str(path)).returncode, 1)

    def test_errors_exit_2(self):
        self.assertEqual(self.run_cli("scan", str(FIXTURES / "nope.html")).returncode, 2)
        path = FIXTURES / "web" / "slop" / "web-pill-dot-outline-badge.html"
        self.assertEqual(self.run_cli("scan", str(path), "--domain", "nosuch").returncode, 2)

    def test_folder_scan_with_forced_domain(self):
        proc = self.run_cli("scan", str(FIXTURES / "copy" / "clean"), "--domain", "copy",
                            "--min-severity", "3")
        self.assertEqual(proc.returncode, 0, proc.stdout)


class ReaderTests(unittest.TestCase):
    def test_png_roundtrip_all_filters_and_channels(self):
        for channels in (1, 2, 3, 4):
            with self.subTest(channels=channels):
                w, h = 7, 11
                data = bytes((x * 37 + y * 11 + c * 5) % 256 for y in range(h) for x in range(w)
                             for c in range(channels))
                img = decode_png(encode_png(w, h, channels, data, filter_cycle=True))
                self.assertEqual((img.width, img.height, img.channels), (w, h, channels))
                self.assertEqual(img.data, data)

    def test_png_palette_and_errors(self):
        ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 3, 0, 0, 0)
        raw = zlib.compress(b"\x00\x00\x01")
        blob = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + \
            _chunk(b"PLTE", bytes([255, 0, 0, 0, 0, 255])) + _chunk(b"IDAT", raw) + \
            _chunk(b"IEND", b"")
        img = decode_png(blob)
        self.assertEqual(list(img.rgb_rows()), [[(255, 0, 0), (0, 0, 255)]])
        interlaced = struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 1)
        with self.assertRaises(PngError):
            decode_png(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", interlaced) + _chunk(b"IEND", b""))
        with self.assertRaises(PngError):
            decode_png(b"not a png")

    def _cube_buffers(self):
        verts = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                 (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
        quads = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [3, 7, 6, 2], [0, 4, 7, 3],
                 [1, 2, 6, 5]]
        idx = [i for q in quads for i in (q[0], q[1], q[2], q[0], q[2], q[3])]
        pos = b"".join(struct.pack("<3f", *v) for v in verts)
        ind = b"".join(struct.pack("<H", i) for i in idx)
        doc = {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": len(pos) + len(ind), "uri": "cube.bin"}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
                            {"buffer": 0, "byteOffset": len(pos), "byteLength": len(ind)}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3"},
                          {"bufferView": 1, "componentType": 5123, "count": len(idx),
                           "type": "SCALAR"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
            "nodes": [{"mesh": 0, "translation": [5, 0, 0]}],
            "scenes": [{"nodes": [0]}],
        }
        return doc, pos + ind

    def test_gltf_sidecar_buffer_and_transform(self):
        doc, blob = self._cube_buffers()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "cube.bin").write_bytes(blob)
            path = Path(tmp) / "cube.gltf"
            path.write_text(json.dumps(doc), encoding="utf-8")
            res = core.scan_file(path, ["model3d"])
            self.assertEqual(res.errors, [])
            self.assertIn("model3d-default-material-only", {f.recognition_id for f in res.findings})
            from scanners.mesh_reader import read_mesh
            mesh = read_mesh(path)
            self.assertEqual(len(mesh.faces), 12)
            self.assertAlmostEqual(min(p[0] for p in mesh.positions), 4.0)

    def test_glb_binary_chunk(self):
        doc, blob = self._cube_buffers()
        del doc["buffers"][0]["uri"]
        js = json.dumps(doc).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        blob += b"\x00" * ((4 - len(blob) % 4) % 4)
        glb = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(blob)) + \
            struct.pack("<II", len(js), 0x4E4F534A) + js + \
            struct.pack("<II", len(blob), 0x004E4942) + blob
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cube.glb"
            path.write_bytes(glb)
            from scanners.mesh_reader import read_mesh
            self.assertEqual(len(read_mesh(path).faces), 12)

    def test_gltf_embedded_data_uri(self):
        doc, blob = self._cube_buffers()
        doc["buffers"][0]["uri"] = "data:application/octet-stream;base64," + \
            base64.b64encode(blob).decode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cube.gltf"
            path.write_text(json.dumps(doc), encoding="utf-8")
            res = core.scan_file(path, ["model3d"])
            self.assertEqual(res.errors, [])

    def test_tui_raw_escapes_and_carriage_return_frames(self):
        frames = "\r".join(f"⠋ Thinking..." if i % 2 == 0 else "⠙ Thinking..."
                           for i in range(6))
        text = ("\x1b[31mone\x1b[0m \x1b[32mtwo\x1b[0m \x1b[33mthree\x1b[0m \x1b[34mfour\x1b[0m\n"
                + frames + "\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.ansi"
            path.write_bytes(text.encode("utf-8"))
            ids = {f.recognition_id for f in core.scan_file(path, ["tui"]).findings}
            self.assertIn("tui-rainbow-ansi", ids)
            self.assertIn("tui-fake-progress", ids)

    def test_copy_ignores_code_spans_and_fences(self):
        text = ("# Notes\n\nThe word `elevate` is quoted.\n\n```\nUnlock seamless value\n```\n"
                "Plain sentence with a fact: 12 files changed.\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text(text, encoding="utf-8")
            res = core.scan_file(path, ["copy"])
            self.assertEqual([f.rule_id for f in res.findings], [])

    def test_unsupported_image_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wood.jpg"
            path.write_bytes(b"\xff\xd8\xff")
            res = core.scan_file(path)
            self.assertTrue(res.errors)
            self.assertIn("PNG", res.errors[0])


if __name__ == "__main__":
    unittest.main()
