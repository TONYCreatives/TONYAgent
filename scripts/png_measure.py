"""Measure a screenshot into a stylesheet.

Every colour and every length in `app/src/styles.css` came out of a screenshot of
the Freebuff window running on this machine, and this is the tool that read it.
A screenshot cannot be looked at and then transcribed accurately -- the eye
reports "dark grey" for #292b2a and "about 200px" for 255 -- so the pixels are
decoded and reported as numbers instead.

Pure stdlib: PNG is zlib plus five scanline filters, which is less code than a
dependency would be, in a repo that has none.

**Capture at full DPI or every number here is wrong.** On this machine the
display is at 1.75 scale, and a screenshot taken by a DPI-unaware process comes
out in *logical* pixels -- 1655x990 for a window that is really 2879x1799. Every
figure measured off such a capture was short by that factor, which is how the
sidebar came to be documented as 204px when it is 307 and the title bar as 46px
when it is 48. `scripts/shot_screen.ps1` opts into PER_MONITOR_AWARE_V2 for
exactly this reason.

Usage:
    python scripts/png_measure.py shot.png
    python scripts/png_measure.py shot.png --scale 1.75 --rows 40,600,1500 --cols 45,1439
    python scripts/png_measure.py shot.png --palette 12

Options:
    --scale N   device scale factor; physical pixels are divided by it to give
                CSS pixels. Default: read from the image's own DPI chunk when
                present, else 1.
    --rows      physical-pixel y coordinates, printed as colour runs across
    --cols      physical-pixel x coordinates, printed as colour runs down
    --palette   how many colours of the histogram to print (default 10)
"""

from __future__ import annotations

import struct
import sys
import zlib
from collections import Counter
from pathlib import Path


def read_png(path: Path) -> tuple[int, int, list[tuple[int, int, int]], float]:
    """Decode a non-interlaced 8-bit PNG into a flat row-major pixel list.

    Returns the size, the pixels, and the horizontal scale the file claims in its
    pHYs chunk. A screenshot carries that chunk, and it is how the scale factor
    stops being a guess.
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    pos, idat, header, ppu = 8, bytearray(), None, None
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"pHYs":
            ppu = struct.unpack(">IIB", body)[0]
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    if header is None:
        raise ValueError("no header")
    width, height, depth, colour, _comp, _filt, interlace = header
    if depth != 8 or interlace != 0 or colour not in (0, 2, 6):
        raise ValueError(f"unsupported png: depth={depth} colour={colour}")
    channels = {0: 1, 2: 3, 6: 4}[colour]
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out: list[tuple[int, int, int]] = []
    previous = bytearray(stride)
    offset = 0
    for _row in range(height):
        method = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += 1 + stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            if method == 1:
                line[i] = (line[i] + a) & 0xFF
            elif method == 2:
                line[i] = (line[i] + b) & 0xFF
            elif method == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif method == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        previous = line
        for x in range(width):
            base = x * channels
            if channels == 1:
                out.append((line[base], line[base], line[base]))
            else:
                out.append((line[base], line[base + 1], line[base + 2]))
    # pHYs is pixels-per-metre; 1 inch is 0.0254 m, so scale = ppu / (1/0.0254).
    scale = ppu / 39.3701 if ppu else 1.0
    return width, height, out, scale


def hex_of(colour: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % colour


def runs_of(line, tolerance: int = 6, minimum: int = 3):
    """Runs of near-identical colour.

    The tolerance is what makes this readable at all: antialiased text shatters a
    row into hundreds of one-pixel runs otherwise. It is also a trap -- a run is
    reported in the colour of its *first* pixel, so a wide run that starts on a
    hairline border reports the border's colour. Sample a 3x3 patch when the
    answer matters.
    """
    out, start, current = [], 0, line[0]
    for i in range(1, len(line)):
        if all(abs(line[i][c] - current[c]) <= tolerance for c in range(3)):
            continue
        out.append((start, i, current))
        start, current = i, line[i]
    out.append((start, len(line), current))
    return [r for r in out if r[1] - r[0] >= minimum]


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        return 2
    path = Path(args[0])
    rest = args[1:]

    def option(name: str, fallback: str) -> str:
        if name in rest:
            return rest[rest.index(name) + 1]
        for i, a in enumerate(rest):
            if a.startswith(name + "="):
                return a.split("=", 1)[1]
        return fallback

    width, height, pixels, scale = read_png(path)
    scale = float(option("--scale", str(scale)))
    how_many = int(option("--palette", "10"))
    rows = [int(v) for v in option("--rows", "").split(",") if v]
    cols = [int(v) for v in option("--cols", "").split(",") if v]
    if not rows and not cols:
        rows, cols = [4, 40, height // 2], []

    print(f"=== {path.name}  {width}x{height} physical, scale {scale} ===")
    if abs(scale - 1.0) < 1e-6:
        print("  (no pHYs chunk and no --scale: these are CSS px as read)")

    counts = Counter(pixels)
    total = len(pixels)
    print(f"\n  {len(counts)} distinct colours; top {how_many}:")
    running = 0
    for colour, times in counts.most_common(how_many):
        running += times
        print(
            "    %s  %9d  %5.2f%%  cumulative %5.1f%%"
            % (hex_of(colour), times, 100 * times / total, 100 * running / total)
        )
    chromatic = sum(1 for c in pixels if max(c) - min(c) > 6)
    print(
        "    chromatic (max-min > 6): %d px = %.3f%%"
        % (chromatic, 100 * chromatic / total)
    )

    for y in rows:
        if not 0 <= y < height:
            continue
        print(f"\n  row y={y}  (css {y / scale:.1f})")
        for start, end, colour in runs_of([pixels[y * width + x] for x in range(width)]):
            print(
                "    x %5d .. %5d  %4d px  css %7.1f .. %7.1f  %s"
                % (start, end, end - start, start / scale, end / scale, hex_of(colour))
            )

    for x in cols:
        if not 0 <= x < width:
            continue
        print(f"\n  column x={x}  (css {x / scale:.1f})")
        for start, end, colour in runs_of([pixels[y * width + x] for y in range(height)]):
            print(
                "    y %5d .. %5d  %4d px  css %7.1f .. %7.1f  %s"
                % (start, end, end - start, start / scale, end / scale, hex_of(colour))
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))