"""Let the agent look at the screen the user is actually looking at.

``browser_screenshot`` already exists and saves a page into the project folder,
but it photographs a headless browser inside a container: the model can see what
it navigated to and nothing at all about the machine the user is sitting at.
This is the other half, and it is a genuinely different capability -- it is the
only tool that can put pixels the user did not ask to share in front of a model.

**Which is why it is gated to Full and to Full only.** `browser_screenshot` is
observation of something the agent itself caused; this is observation of the
user's desktop, which holds everything else they have open. Full is the rung
whose own description says commands run on this computer outside the project
folder, so a capture is the same bargain the user already agreed to, and the
tool says so in the refusal rather than pretending the restriction is technical.

Two refusals, on purpose:

  * Below Full the orchestrator's allow-list stops the call before it gets here,
    and the tool checks ``host_execution()`` as well so a future allow-list that
    drifts cannot quietly widen this.
  * A region that is not entirely inside the captured desktop is refused. Half a
    screenshot that falls off the edge is a screenshot the model will describe
    confidently and wrongly.

**The image goes to the model, not to a file.** No path is written and nothing
is left on disk: the pixels are attached to the tool message and are gone when
the turn ends. `browser_screenshot` writes because its output is something to
keep; this output is something to look at.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from tonyagent.tools.base import (
    Tool,
    ToolCategory,
    ToolResult,
    ToolResultStatus,
    register_tool,
)
# The encoder is shared with `read_image`, so the downscale -- and the way it is
# described to the model -- cannot drift between the two tools that hand over a
# picture. `MAX_EDGE` is imported as a module-level name on purpose: it is passed
# to `encode` explicitly below, so patching `screen_tools.MAX_EDGE` still changes
# what happens. Reading the global inside `images` would make that patch silently
# ineffective, and its tests rely on it.
from tonyagent.tools.images import EDGE_NOTE, MAX_EDGE, encode
from tonyagent.tools.shell_tools import host_execution

#: Shown when a capture is refused because the permission rung is below Full.
NOT_FULL = (
    "This tool reads the screen on this computer, so it is available at Full "
    "permission only, where commands already run on this machine rather than in "
    "a sandbox. Raise the permission to Full to use it."
)


def _grab(bbox: tuple[int, int, int, int] | None) -> Any:
    """The capture itself, imported lazily so the module imports anywhere."""
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=bbox, all_screens=True)


def _region(
    x: int | None, y: int | None, width: int | None, height: int | None
) -> tuple[tuple[int, int, int, int] | None, str | None]:
    """Validate a region, returning the bbox PIL wants or a reason to refuse.

    All four or none of them. Half a region is the one shape that is genuinely
    ambiguous -- a width with no x is "from where?" -- and answering it by
    guessing would put the wrong pixels in front of the model with no signal
    that anything was wrong.
    """
    given = [v for v in (x, y, width, height) if v is not None]
    if not given:
        return None, None
    if len(given) != 4:
        return None, (
            "Give all four of x, y, width and height, or none of them to capture "
            "the whole screen."
        )
    assert x is not None and y is not None and width is not None and height is not None
    if width <= 0 or height <= 0:
        return None, f"Region must be bigger than nothing: {width}x{height}."
    if x < 0 or y < 0:
        return None, (
            f"Region starts at ({x}, {y}). Screen coordinates start at the top "
            "left of the virtual desktop and cannot be negative."
        )
    return (x, y, x + width, y + height), None


@register_tool
class TakeScreenshotTool(Tool):
    """Capture the screen and hand the image straight back to the model."""

    name = "take_screenshot"
    description = (
        "Take a screenshot of this computer's screen and look at it. Full "
        "screen unless a region is given, in which case all four of x, y, "
        "width and height are required and are in virtual-desktop pixels from "
        "the top left. Use it when the answer is in what the user can see -- an "
        "error dialog, a layout, what is on the screen right now."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "x": {
                "type": "integer",
                "description": "Left edge of the region, in pixels from the top left.",
            },
            "y": {
                "type": "integer",
                "description": "Top edge of the region, in pixels from the top left.",
            },
            "width": {"type": "integer", "description": "Region width in pixels."},
            "height": {"type": "integer", "description": "Region height in pixels."},
        },
        "additionalProperties": False,
    }
    destructive = False
    # Not asked for on Full, which is the only rung that reaches here: the user
    # has already said that whatever happens happens. Below Full the call is
    # refused outright, so there is nothing to confirm.
    requires_confirmation = False
    # The screen is the host's, by definition. No container can be asked for
    # this, and pretending otherwise would mean a tool that is dead in the
    # sandbox and alive outside it for no stated reason.
    sandbox_required = False
    isolation_required = False

    async def execute(
        self,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> ToolResult:
        if not host_execution():
            return ToolResult(status=ToolResultStatus.ERROR, error=NOT_FULL)

        bbox, reason = _region(x, y, width, height)
        if reason:
            return ToolResult(status=ToolResultStatus.ERROR, error=reason)

        try:
            desktop = _grab(None)
        except Exception as exc:  # noqa: BLE001 - the model gets the real reason
            logger.warning(f"Screenshot failed: {exc}")
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Could not capture the screen: {exc}",
            )

        bounds = desktop.size
        if bbox is not None and (bbox[2] > bounds[0] or bbox[3] > bounds[1]):
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    f"Region ends at ({bbox[2]}, {bbox[3]}) but the screen is "
                    f"{bounds[0]}x{bounds[1]}. A capture that runs off the edge "
                    "would come back with part of it missing."
                ),
            )

        try:
            image = _grab(bbox) if bbox is not None else desktop
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Screenshot of a region failed: {exc}")
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Could not capture that region: {exc}",
            )

        part, original_w, original_h, out_w, out_h = encode(image, max_edge=MAX_EDGE)
        said = (
            f"Captured a region of the screen at {bbox[0]},{bbox[1]} "
            f"{original_w}x{original_h}."
            if bbox is not None
            else f"Captured the whole screen, {original_w}x{original_h}."
        )
        if (out_w, out_h) != (original_w, original_h):
            said += " " + EDGE_NOTE.format(
                ow=original_w, oh=original_h, w=out_w, h=out_h
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=said,
            # The model needs to know where the pixels are, or it will describe
            # the whole desktop when it was handed a corner of it.
            artifacts=[
                {
                    "type": "screenshot",
                    "region": list(bbox) if bbox else None,
                    "captured": [original_w, original_h],
                    "sent_as": [out_w, out_h],
                }
            ],
            images=[part],
        )