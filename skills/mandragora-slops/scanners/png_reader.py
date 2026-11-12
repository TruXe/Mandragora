"""Minimal PNG decoder and encoder built on zlib (standard library only).

Decodes non-interlaced PNG with 8-bit samples for gray (0), RGB (2),
palette (3), gray+alpha (4) and RGBA (6). 16-bit gray/RGB/RGBA is accepted
and reduced to 8 bits by keeping the high byte. All five scanline filters
are supported. Interlaced (Adam7) files and sub-byte depths raise PngError.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
# Decoding cost is linear in pixels; this cap keeps pure-Python runs bounded.
MAX_PIXELS = 4096 * 4096


class PngError(ValueError):
    pass


@dataclass
class Image:
    width: int
    height: int
    channels: int          # 1 gray, 2 gray+alpha, 3 RGB, 4 RGBA (palette is expanded)
    data: bytes            # row-major 8-bit samples, len = width * height * channels

    def rgb_rows(self):
        """Yield rows as lists of (r, g, b) tuples."""
        w, ch = self.width, self.channels
        for y in range(self.height):
            row = self.data[y * w * ch:(y + 1) * w * ch]
            if ch == 1:
                yield [(v, v, v) for v in row]
            elif ch == 2:
                yield [(row[i], row[i], row[i]) for i in range(0, len(row), 2)]
            elif ch == 3:
                yield [(row[i], row[i + 1], row[i + 2]) for i in range(0, len(row), 3)]
            else:
                yield [(row[i], row[i + 1], row[i + 2]) for i in range(0, len(row), 4)]


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytearray:
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        if pos >= len(raw):
            raise PngError("image data ends early")
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        if len(line) != stride:
            raise PngError("truncated scanline")
        pos += 1 + stride
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 0xFF
        else:
            raise PngError(f"unknown filter type {ftype} on row {y}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def decode_png(blob: bytes) -> Image:
    if not blob.startswith(PNG_SIGNATURE):
        raise PngError("not a PNG file (bad signature)")
    pos = len(PNG_SIGNATURE)
    header = None
    palette = None
    trns = None
    idat = []
    while pos + 8 <= len(blob):
        length, ctype = struct.unpack(">I4s", blob[pos:pos + 8])
        body = blob[pos + 8:pos + 8 + length]
        crc = blob[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4:
            raise PngError(f"truncated chunk {ctype!r}")
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != struct.unpack(">I", crc)[0]:
            raise PngError(f"CRC mismatch in chunk {ctype!r}")
        pos += 12 + length
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif ctype == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif ctype == b"tRNS":
            trns = body
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
    if header is None:
        raise PngError("missing IHDR")
    width, height, depth, ctype_, _comp, _filt, interlace = header
    if ctype_ not in CHANNELS:
        raise PngError(f"unsupported color type {ctype_}")
    if interlace:
        raise PngError("interlaced (Adam7) PNG is not supported; re-save without interlacing")
    if depth not in (8, 16) or (ctype_ == 3 and depth != 8):
        raise PngError(f"bit depth {depth} for color type {ctype_} is not supported")
    if width * height > MAX_PIXELS:
        raise PngError(f"{width}x{height} exceeds the {MAX_PIXELS} pixel limit")
    ch = CHANNELS[ctype_]
    bpp = ch * depth // 8
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise PngError(f"corrupt image data: {exc}") from exc
    pixels = _unfilter(raw, height, stride, bpp)
    if depth == 16:
        pixels = pixels[0::2]
    if ctype_ == 3:
        if not palette:
            raise PngError("palette image without PLTE")
        alpha = list(trns) if trns else []
        out_ch = 4 if alpha else 3
        expanded = bytearray()
        for idx in pixels:
            r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
            expanded.extend((r, g, b))
            if alpha:
                expanded.append(alpha[idx] if idx < len(alpha) else 255)
        return Image(width, height, out_ch, bytes(expanded))
    return Image(width, height, ch, bytes(pixels))


def read_png(path) -> Image:
    return decode_png(Path(path).read_bytes())


def _chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + \
        struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def encode_png(width: int, height: int, channels: int, data: bytes, filter_cycle: bool = False) -> bytes:
    """Encode 8-bit gray/gray+alpha/RGB/RGBA. With filter_cycle each row uses
    filter type (row % 5), which exercises every unfilter path when decoded."""
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    stride = width * channels
    raw = bytearray()
    prev = bytearray(stride)
    for y in range(height):
        line = bytearray(data[y * stride:(y + 1) * stride])
        ftype = y % 5 if filter_cycle else 0
        enc = bytearray(stride)
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            pred = (0, a, b, (a + b) >> 1, _paeth(a, b, c))[ftype]
            enc[i] = (line[i] - pred) & 0xFF
        raw.append(ftype)
        raw.extend(enc)
        prev = line
    ihdr = struct.pack(">IIBBBBB", width, height, 8, ctype, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) \
        + _chunk(b"IEND", b"")
