"""A `grab` / `grabbing` cursor pair, drawn and written as real Windows cursors.

Windows has no open-hand cursor: `IDC_HAND` is the pointing hand, `IDC_SIZEALL` is the
four-way move arrow. Neither is the web's `cursor: grab`, which is what a draggable
thing should show -- so the pair is drawn here and written as 32-bit `.cur` files.

The format is old but small, and 32-bit is what makes it worth doing: since Windows
Vista a cursor's bitmap may carry an **alpha channel**, so the hand is antialiased
rather than the 1-bit black-and-white of `CreateCursor`. Same bet as the window: put
the shape in the alpha.

Import `load()` from the pet window; run this file directly to write the previews and
look at them.
"""

import ctypes
import pathlib
import struct
from ctypes import wintypes

from PIL import Image, ImageDraw

#: The cursor's own colours: the app's pale ink on its dark surface, with a dark rim
#: so the hand reads over both a light wallpaper and a dark one.
INK = (238, 238, 238, 255)
RIM = (24, 24, 26, 255)

SIZE = 32
#: Where the hand "holds": the middle of the palm.
HOTSPOT = (16, 18)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
IMAGE_CURSOR = 2
LR_LOADFROMFILE = 0x00000010


def _rounded(draw: ImageDraw.ImageDraw, box: tuple, radius: int) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=INK, outline=RIM, width=1)


def hand(closed: bool) -> Image.Image:
    """An open hand (`grab`) or a fist (`grabbing`), drawn as overlapping blobs.

    Each part is filled and outlined, so the outlines that meet read as the creases
    between fingers -- which is what makes it legible at 32 pixels.
    """
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if closed:
        # A fist: the fingers curled down, so only their knuckles show.
        _rounded(draw, (7, 14, 26, 28), 5)          # palm
        _rounded(draw, (8, 11, 12, 17), 2)          # knuckles
        _rounded(draw, (12, 9, 16, 16), 2)
        _rounded(draw, (16, 9, 20, 16), 2)
        _rounded(draw, (20, 11, 24, 17), 2)
        _rounded(draw, (4, 15, 10, 24), 3)          # thumb across
    else:
        # An open hand, fingers up at slightly different heights.
        _rounded(draw, (7, 15, 26, 28), 5)          # palm
        _rounded(draw, (9, 6, 13, 19), 2)           # fingers
        _rounded(draw, (13, 4, 17, 19), 2)
        _rounded(draw, (17, 4, 21, 19), 2)
        _rounded(draw, (21, 8, 25, 19), 2)
        _rounded(draw, (3, 14, 10, 24), 3)          # thumb
    return image


def to_cur(image: Image.Image, hotspot: tuple, path: pathlib.Path) -> pathlib.Path:
    """Write a 32-bit cursor: `ICONDIR`, one entry, then a 32bpp DIB.

    The DIB is a `BITMAPINFOHEADER` whose height is **twice** the image: the colour
    bitmap followed by the AND mask, both bottom-up. For a 32-bit cursor the mask is
    vestigial -- the alpha decides -- so it is written as zeroes.
    """
    pixels = image.convert("RGBA")
    width, height = pixels.size
    colour = bytearray()
    for y in range(height - 1, -1, -1):  # bottom-up
        for x in range(width):
            r, g, b, a = pixels.getpixel((x, y))
            colour += bytes((b, g, r, a))
    mask_stride = ((width + 31) // 32) * 4
    mask = bytes(mask_stride * height)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,               # biSize
        width,            # biWidth
        height * 2,       # biHeight: colour + mask
        1,                # biPlanes
        32,               # biBitCount
        0,                # biCompression: BI_RGB
        len(colour) + len(mask),
        0, 0, 0, 0,
    )
    dib = header + bytes(colour) + mask
    entry = struct.pack(
        "<BBBBHHII",
        width, height, 0, 0,
        hotspot[0], hotspot[1],
        len(dib), 6 + 16,  # bytes in resource, offset of the image
    )
    path.write_bytes(struct.pack("<HHH", 0, 2, 1) + entry + dib)
    return path


def load(directory: pathlib.Path) -> tuple:
    """Write the pair and return `(grab, grabbing)` as `HCURSOR`s.

    `LoadImageW` with `LR_LOADFROMFILE` reads a `.cur` off disk, which is the only way
    to get alpha into a cursor -- `CreateCursor` is 1-bit.
    """
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    directory.mkdir(parents=True, exist_ok=True)
    made = []
    for name, closed in (("grab", False), ("grabbing", True)):
        path = to_cur(hand(closed), HOTSPOT, directory / f"{name}.cur")
        handle = user32.LoadImageW(None, str(path), IMAGE_CURSOR, 0, 0, LR_LOADFROMFILE)
        if not handle:
            raise OSError(f"LoadImageW refused {path}: {ctypes.GetLastError()}")
        made.append(handle)
    return tuple(made)


if __name__ == "__main__":
    out = pathlib.Path(".tmp-cursors")
    grab, grabbing = load(out)
    print("loaded:", grab, grabbing)
    # Side by side, magnified, so they can actually be looked at.
    sheet = Image.new("RGBA", (SIZE * 2 + 24, SIZE + 16), (60, 60, 68, 255))
    for index, closed in enumerate((False, True)):
        sheet.alpha_composite(hand(closed), (8 + index * (SIZE + 8), 8))
    preview = pathlib.Path(".tmp-cursors-preview.png")
    sheet.resize((sheet.width * 6, sheet.height * 6), Image.NEAREST).save(preview)
    print("preview:", preview)
