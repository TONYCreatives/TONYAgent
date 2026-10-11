"""Turning a picture into something a model can be handed.

One home for the image path, for the reason ``runtime_access`` is one home for
the runtime decision: two copies of "downscale to what the model accepts" would
eventually disagree about the number, and the cost of that disagreement is paid
in tokens on every call that carries a picture. Two tools produce images --
``take_screenshot``, which captures the screen, and ``read_image``, which reads a
file -- and they must not describe the same downscale to the model two different
ways.

The limit is a *cost* limit as much as an acceptance one: a 4K capture sent
faithfully is roughly 8x the tokens of the same picture at this size, for no
detail a model can act on.
"""

from __future__ import annotations

import base64
import io
from typing import Any

#: Longest edge, in pixels, of an image handed to the model.
#:
#: 1568 is the number OpenAI's own vision guidance uses for the large edge. A
#: window's 12pt text is already below the limit at this scale, so the saving is
#: entirely in the parts nobody reads.
MAX_EDGE = 1568

#: Largest source file ``read_image`` will open, before any downscaling.
#:
#: The file is decoded in full in order to be resized, so this bounds *memory*
#: rather than tokens: without it a tool call could ask the process to hold a file
#: larger than the machine is willing to. 32 MB is comfortably above a phone
#: photo and well below anything that would hurt.
MAX_SOURCE_BYTES = 32 * 1024 * 1024

#: How a downscale is described back to the model, so it can correct itself.
EDGE_NOTE = (
    "Downscaled from {ow}x{oh} to {w}x{h} for the model's input limit; layout, "
    "text and colour are unchanged, fine detail is not."
)


def _lanczos() -> Any:
    from PIL import Image

    return Image.Resampling.LANCZOS


def encode(
    image: Any, max_edge: int | None = None
) -> tuple[dict[str, str], int, int, int, int]:
    """Downscale if needed, then base64. Returns the part and both sizes.

    ``max_edge`` is an argument rather than a straight read of the module global
    so a caller can hold its own name for the limit: ``screen_tools`` does, and
    its tests patch that name to exercise both sides of the resize. Reading the
    global directly here would make those patches silently ineffective.
    """
    limit = MAX_EDGE if max_edge is None else max_edge

    # PNG cannot represent every mode Pillow can produce, and a CMYK or
    # palette image fails at *save* time rather than at open time -- an error
    # from deep inside the encoder, about a file that opened perfectly well.
    # Normalised here so both callers get the same treatment.
    if image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

    original_w, original_h = image.size
    longest = max(original_w, original_h)
    if longest > limit:
        scale = limit / longest
        # Round rather than truncate: a 2560x1440 capture is 1568x882 exactly,
        # and int() would give 881 and a one-pixel smear of the wrong aspect.
        image = image.resize(
            (round(original_w * scale), round(original_h * scale)),
            # LANCZOS rather than the default. Downscaling a screenshot with
            # NEAREST drops every other row of small text, which is the one
            # thing a model is looking at the picture to read.
            _lanczos(),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return (
        {
            "mime": "image/png",
            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
        },
        original_w,
        original_h,
        image.size[0],
        image.size[1],
    )
