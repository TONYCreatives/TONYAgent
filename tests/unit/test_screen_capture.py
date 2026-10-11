"""The screenshot tool: what it may see, what the model gets, what reaches disk.

`ImageGrab` is faked throughout. The alternative is a test suite that captures
the developer's actual desktop -- which is slow, flaky, and would put their
screen into a CI log the first time it ran.

The three claims worth having tests for, in the order they can break:

  * **Permission.** A capture is refused below Full and returns no pixels.
  * **Region.** All four coordinates or none, inside the screen, non-empty --
    because a partly-missing screenshot is described confidently and wrongly.
  * **The image reaches the model but not the disk.** Those are two different
    code paths (`_tool_content` and `strip_images`) and the second one is the
    only thing keeping a saved conversation from filling up with base64.
"""

import asyncio
import base64
import io
import json

import pytest
from PIL import Image

from tonyagent.core.attachments import strip_images
from tonyagent.core.session import AgentSession
from tonyagent.providers.base import ChatMessage
from tonyagent.tools import screen_tools
from tonyagent.tools.base import ToolResultStatus
from tonyagent.tools.shell_tools import set_host_execution

#: 1440x810 rather than a real 1920x1080 desktop. 16:9, and -- the reason it
#: matters -- smaller than `MAX_EDGE`, so "what the tool returns" and "what the
#: tool downscales" are two different tests rather than one that silently
#: exercises the resampler every time. A test that asserts a whole-screen
#: capture comes back at desktop size is only true on a desktop small enough to
#: need no resizing.
DESKTOP = (1440, 810)


@pytest.fixture(autouse=True)
def fake_screen(monkeypatch):
    """A desktop of a known size, and Full permission restored afterwards.

    The grab is replaced rather than the mode: `MAX_EDGE` stays real, so the
    downscaling path is exercised whenever a test makes the desktop big enough.
    """
    def grab(bbox=None, all_screens=False):
        box = bbox or (0, 0, *DESKTOP)
        w, h = box[2] - box[0], box[3] - box[1]
        assert w > 0 and h > 0, f"the tool asked for an empty bbox: {bbox}"
        return Image.new("RGB", (w, h), (20, 20, 20))

    monkeypatch.setattr(screen_tools, "_grab", grab)
    set_host_execution(True)
    yield
    set_host_execution(False)


def call(**kwargs):
    return asyncio.run(screen_tools.TakeScreenshotTool().execute(**kwargs))


def decoded(result):
    """The image a result carries, opened rather than trusted."""
    assert len(result.images) == 1, result.images
    raw = base64.b64decode(result.images[0]["data"])
    return Image.open(io.BytesIO(raw))


class TestPermission:
    def test_below_full_it_refuses_and_returns_no_pixels(self):
        # The refusal has to name the rung, or the model retries a tool that
        # cannot work and burns the turn's budget finding out.
        set_host_execution(False)
        result = call()
        assert result.status is ToolResultStatus.ERROR
        assert "Full" in result.error
        assert result.images == []
        assert result.artifacts == []

    def test_at_full_it_captures(self):
        result = call()
        assert result.status is ToolResultStatus.SUCCESS
        assert decoded(result).size == DESKTOP

    def test_the_allow_list_agrees_with_the_check(self):
        # Two gates that both say "Full". They are separate on purpose -- the
        # allow-list stops the call, the check stops a future drift -- so a
        # change to one without the other is a real hole and this is what sees
        # it.
        from tonyagent.core.modes import PERMISSION_ORDER, PERMISSIONS

        allowed = {
            name for name in PERMISSION_ORDER
            if "take_screenshot" in PERMISSIONS[name].allowed_tools
        }
        assert allowed == {"full"}


class TestRegion:
    def test_the_whole_screen_when_nothing_is_given(self):
        result = call()
        assert result.artifacts[0]["region"] is None
        assert decoded(result).size == DESKTOP

    def test_a_region_is_exactly_that_region(self):
        result = call(x=100, y=50, width=800, height=600)
        assert result.status is ToolResultStatus.SUCCESS
        assert decoded(result).size == (800, 600)
        assert result.artifacts[0]["region"] == [100, 50, 900, 650]
        # The model has to be told it is looking at part of the screen, or it
        # will describe a window that was never in the picture.
        assert "region" in result.output

    @pytest.mark.parametrize(
        "kwargs, why",
        [
            ({"x": 10}, "x alone"),
            ({"x": 10, "y": 10}, "x and y"),
            ({"width": 10}, "width alone"),
            ({"height": 10}, "height alone"),
            ({"x": 0, "y": 0, "width": 0, "height": 10}, "zero width"),
            ({"x": 0, "y": 0, "width": 10, "height": 0}, "zero height"),
            ({"x": -5, "y": 0, "width": 10, "height": 10}, "negative x"),
            ({"x": 0, "y": 0, "width": 5000, "height": 10}, "past the right edge"),
            ({"x": 0, "y": 0, "width": 10, "height": 5000}, "past the bottom"),
        ],
    )
    def test_a_region_it_cannot_honour_is_refused(self, kwargs, why):
        # Every one of these is a way the model could ask for a picture it did
        # not describe, and the failure mode is a confident wrong description
        # rather than an error.
        result = call(**kwargs)
        assert result.status is ToolResultStatus.ERROR, why
        assert result.images == [], why
        assert result.error

    def test_the_right_edge_exactly_is_allowed(self):
        # Off-by-one: ending at 1920 is the last column, not past it.
        result = call(x=1340, y=730, width=100, height=80)
        assert result.status is ToolResultStatus.SUCCESS, result.error
        assert decoded(result).size == (100, 80)


class TestSize:
    def test_a_small_capture_is_not_touched(self, monkeypatch):
        monkeypatch.setattr(screen_tools, "MAX_EDGE", 5000)
        result = call()
        assert decoded(result).size == DESKTOP
        assert "Downscaled" not in result.output

    def test_a_large_one_is_scaled_down_and_says_so(self, monkeypatch):
        # The aspect ratio has to survive: a 16:9 screen squashed to 16:10 makes
        # a model describe a layout that does not exist.
        monkeypatch.setattr(screen_tools, "MAX_EDGE", 800)
        result = call()
        assert decoded(result).size == (800, 450)
        assert "1440x810" in result.output
        assert "800x450" in result.output
        assert result.artifacts[0]["captured"] == [1440, 810]
        assert result.artifacts[0]["sent_as"] == [800, 450]

    def test_a_scaled_region_keeps_its_own_ratio(self, monkeypatch):
        monkeypatch.setattr(screen_tools, "MAX_EDGE", 400)
        result = call(x=0, y=0, width=1440, height=600)
        assert decoded(result).size == (400, 167)


class TestReachesTheModel:
    @staticmethod
    def content_for(result):
        payload = result.to_dict()
        return AgentSession._tool_content(payload, result)

    def test_the_image_is_a_content_part_and_not_a_path(self):
        content = self.content_for(call())
        # A path would mean the model has to ask again with another tool, which
        # is the extra round trip this tool exists to avoid.
        assert isinstance(content, list)
        assert [part["type"] for part in content] == ["text", "image_url"]
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert json.loads(content[0]["text"])["status"] == "success"

    def test_the_words_come_before_the_picture(self):
        content = self.content_for(call())
        assert content[0]["type"] == "text", "the JSON must lead; a wall of base64 first is unreadable"

    def test_a_tool_with_no_image_is_still_one_json_string(self):
        # Every other tool in the app. If this changed shape, the whole
        # transcript would.
        class Bare:
            images = []

        content = AgentSession._tool_content({"output": "hi"}, Bare())
        assert isinstance(content, str)
        assert json.loads(content)["output"] == "hi"

    def test_the_provider_receives_the_parts_unchanged(self):
        # `ChatMessage.to_dict` is the only thing between this and the wire, and
        # it is where a list content could be flattened to a string.
        message = ChatMessage(role="tool", content=self.content_for(call()), tool_call_id="c1")
        wire = message.to_dict()
        assert wire["role"] == "tool"
        assert wire["tool_call_id"] == "c1"
        assert wire["content"][1]["image_url"]["url"].startswith("data:image/png;")


class TestDoesNotReachDisk:
    def test_a_saved_conversation_keeps_no_base64(self):
        message = ChatMessage(
            role="tool", content=AgentSession._tool_content(call().to_dict(), call()), tool_call_id="c1"
        )
        stored = strip_images([message])
        assert [part["type"] for part in stored[0]["content"]] == ["text", "text"]
        assert "base64" not in json.dumps(stored[0])
        assert "not kept" in stored[0]["content"][1]["text"]

    def test_a_conversation_without_images_is_untouched(self):
        message = ChatMessage(role="user", content="just words")
        assert strip_images([message]) == [message.to_dict()]

    def test_text_parts_survive_alongside_the_image(self):
        # Dropping the whole content list would take the result with it, and
        # the model would have an image and no idea what it is a picture of.
        message = ChatMessage(
            role="tool",
            content=[
                {"type": "text", "text": "keep me"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                {"type": "text", "text": "keep me too"},
            ],
        )
        content = strip_images([message])[0]["content"]
        assert content[0] == {"type": "text", "text": "keep me"}
        assert content[2] == {"type": "text", "text": "keep me too"}
        assert content[1]["type"] == "text"

    def test_the_saving_is_much_smaller_than_the_wire(self):
        message = ChatMessage(role="tool", content=AgentSession._tool_content(call().to_dict(), call()))
        assert len(json.dumps(strip_images([message])[0])) < len(json.dumps(message.to_dict()))