#!/usr/bin/env python3
"""
Regenerate the app's raster icons from the art in app/icons/icon.svg.

Tauri is gone; this is the pywebview-era replacement for `tauri icon`. There is
no SVG rasteriser on this machine (no cairosvg / Inkscape / ImageMagick), so the
few simple primitives the icon is drawn from are mirrored here in numpy + Pillow
and rasterised directly. The geometry below MUST match app/icons/icon.svg and the
numbers AppMark.tsx ships (`MARK_RECTS`, `MARK_EYES`); `AppMark.test.tsx` holds
the mark and the file to the same geometry, so keeping this in step is what keeps
the taskbar icon and the in-app mark the same drawing.

Run from anywhere:  python scripts/gen_icons.py

Outputs, into app/icons/:
    32x32.png, 128x128.png, 128x128@2x.png (=256), icon.png (=512),
    icon.ico (16/24/32/48/64/256), icon.icns (macOS; unused on Windows)
And previews, into design-preview/logos/:
    pet-icon-1024.png, pet-icon-sheet.png  (the mark at 16/32/64/256)
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "app" / "icons"
PREVIEW = ROOT / "design-preview" / "logos"

CANVAS = 1024  # the viewBox the artwork draws in
SS = 4  # supersample factor: draw at CANVAS*SS, then downsample with LANCZOS

# --- the artwork, mirrored from icon.svg -------------------------------------
TILE_RX = 228  # rounded-corner radius of the tile, in viewBox units (~22%)
GRAD_FROM = (99, 147, 240)  # #6393f0 -- the accent token, top-left
GRAD_TO = (155, 124, 240)  # #9b7cf0 -- the brand ramp's violet, bottom-right
# crossbar (head) then stem (body): (x, y, w, h); must equal MARK_RECTS.
BODY = [(162, 168, 700, 176), (410, 344, 204, 512)]  # head, then body (MARK_RECTS)
EYES = [(348, 260, 52), (676, 260, 52)]  # MARK_EYES
EYE_INK = (32, 32, 32)  # #202020 -- the surface tone the eyes are carved in


def build(size: int) -> Image.Image:
    """The pet-in-tile, rasterised at `size` px with antialiased edges."""
    n = CANVAS * SS  # the high-res buffer edge length
    coords = np.arange(n, dtype=np.float32)
    # The SVG gradient runs (0,0)->(1024,1024); a point's parameter on that axis
    # is (x + y) / (2 * edge). Built by broadcast rather than mgrid, so the
    # buffer is CANVAS*SS on a side without two companion arrays of the same size.
    t = (coords[None, :] + coords[:, None]) / (2.0 * (n - 1))
    lo = np.asarray(GRAD_FROM, np.float32)
    hi = np.asarray(GRAD_TO, np.float32)
    rgb = lo * (1.0 - t[..., None]) + hi * t[..., None]
    grad = Image.fromarray(rgb.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")

    # The tile is that gradient clipped to a rounded square: transparent corners,
    # the shape the app's icon has always had; the OS rounds on top of it.
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, n - 1, n - 1], radius=round(TILE_RX * SS), fill=255
    )
    tile = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)

    draw = ImageDraw.Draw(tile)
    scale = n / CANVAS
    for x, y, w, h in BODY:  # white head + body, the mark's own two strokes
        draw.rectangle(
            [x * scale, y * scale, (x + w) * scale, (y + h) * scale],
            fill=(255, 255, 255, 255),
        )
    for cx, cy, r in EYES:  # the pet's two eyes, carved in the surface tone
        draw.ellipse(
            [(cx - r) * scale, (cy - r) * scale, (cx + r) * scale, (cy + r) * scale],
            fill=(*EYE_INK, 255),
        )

    # Downsample for antialiasing: a square rect and a circle drawn at SS read as
    # smooth edges at 16px, the size the rasters have to stay crisp at.
    return tile.resize((size, size), Image.LANCZOS)


def sheet() -> Image.Image:
    """The mark at 16/32/64/256 on the app's field, to judge the small sizes."""
    sizes = [16, 32, 64, 256]
    pad, gap = 24, 40
    total = sum(sizes) + gap * (len(sizes) - 1)
    img = Image.new("RGBA", (total, 256 + pad * 2), (26, 26, 26, 255))
    x = 0
    for s in sizes:
        mark = build(s)
        img.paste(mark, (x, pad + (256 - s) // 2), mark)
        x += s + gap
    return img


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)

    for name, s in {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
    }.items():
        build(s).save(ICONS / name)
        print(f"wrote app/icons/{name} ({s}x{s})")

    # One .ico, multi-size, the frames the old one carried.
    build(256).save(
        ICONS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)],
    )
    print("wrote app/icons/icon.ico")

    try:
        build(1024).save(ICONS / "icon.icns", format="ICNS")
        print("wrote app/icons/icon.icns")
    except Exception as exc:  # macOS-only; harmless to skip on Windows
        print(f"skipped icon.icns ({exc})")

    build(1024).save(PREVIEW / "pet-icon-1024.png")
    sheet().save(PREVIEW / "pet-icon-sheet.png")
    print("wrote design-preview/logos/pet-icon-1024.png and pet-icon-sheet.png")


if __name__ == "__main__":
    main()
