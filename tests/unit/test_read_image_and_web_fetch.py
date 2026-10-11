"""``read_image`` and ``web_fetch``: the two tools added with Phase 1.

Each has one property that is the reason it exists and is worth pinning:

* ``read_image`` puts pixels in front of the model through ``ToolResult.images``
  -- the field deliberately excluded from ``to_dict``, because that dict is the
  wire payload *and* the body of the tool message written into every saved
  conversation. A screenshot in there would make one call cost as much disk as
  the rest of the chat. So "the picture is attached" and "the picture is not on
  disk" are both asserted.
* ``web_fetch`` shares ``http_request``'s internal-address guard. Two copies of
  that rule would eventually disagree about which addresses it covers, so the
  test that matters is that both tools produce *the same refusal text* for the
  same URL -- not merely that each of them refuses.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.folder import folder_manager
from tonyagent.tools import tool_registry
from tonyagent.tools.base import ToolResultStatus
from tonyagent.tools.images import MAX_EDGE


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    return tmp_path


@pytest.fixture
def no_folder(monkeypatch):
    """No project folder at all, for the ``folder_required`` question."""
    monkeypatch.setattr(folder_manager, "_current_folder", None)


def tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


def make_image(path: Path, size=(40, 30), mode="RGB"):
    from PIL import Image

    Image.new(mode, size).save(path)
    return path


# --- read_image: the picture reaches the model -------------------------------


async def test_a_png_comes_back_as_a_picture(project):
    make_image(project / "shot.png", size=(40, 30))

    result = await tool("read_image").execute(path="shot.png")

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert len(result.images) == 1
    assert result.images[0]["mime"] == "image/png"

    from PIL import Image

    decoded = Image.open(io.BytesIO(base64.b64decode(result.images[0]["data"])))
    assert decoded.size == (40, 30)
    assert "40x30" in result.output


async def test_the_pixels_are_not_in_the_dict_that_goes_to_disk(project):
    """The reason ``images`` is a separate field and not part of ``to_dict``.

    ``to_dict`` is both the wire payload and the tool message stored in every
    saved conversation, so a picture in there would be megabytes of base64 on
    disk for one call.
    """
    make_image(project / "shot.png")

    result = await tool("read_image").execute(path="shot.png")

    assert result.images, "the picture did not reach the model at all"
    assert "images" not in result.to_dict(), (
        "the base64 pixels are on the dict that is written to disk"
    )


async def test_a_large_image_is_downscaled_and_says_so(project):
    make_image(project / "big.png", size=(4000, 200))

    result = await tool("read_image").execute(path="big.png")

    from PIL import Image

    decoded = Image.open(io.BytesIO(base64.b64decode(result.images[0]["data"])))
    assert max(decoded.size) <= MAX_EDGE, f"sent {decoded.size}, over the limit"
    assert "Downscaled" in result.output, (
        "the model was handed a smaller picture with no indication of it"
    )


async def test_a_small_image_is_not_resized(project):
    """And so does not claim a downscale that did not happen."""
    make_image(project / "small.png", size=(40, 30))

    result = await tool("read_image").execute(path="small.png")

    assert "Downscaled" not in result.output


@pytest.mark.parametrize(
    ("suffix", "mode"),
    [
        (".png", "P"),
        # CMYK is the interesting one and it has to be a TIFF: PNG cannot hold
        # CMYK at all, which is exactly why the mode has to be normalised before
        # saving rather than discovered at save time.
        (".tiff", "CMYK"),
        (".png", "RGBA"),
        (".png", "L"),
    ],
)
async def test_unusual_image_modes_still_encode(project, suffix, mode):
    """PNG cannot represent every mode Pillow can open.

    Without normalising the mode the failure lands in the encoder, about a file
    that opened perfectly well -- so a palette or CMYK image would look like a
    corrupt file rather than an unsupported one.
    """
    from PIL import Image

    name = f"m{mode}{suffix}"
    Image.new(mode, (40, 30)).save(project / name)

    result = await tool("read_image").execute(path=name)

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert len(result.images) == 1


async def test_a_file_that_is_not_an_image_is_refused(project):
    (project / "notes.txt").write_text("just text\n", encoding="utf-8")

    result = await tool("read_image").execute(path="notes.txt")

    assert result.status is ToolResultStatus.ERROR
    assert result.images == [], "pixels were sent for a file that has none"
    assert "not an image" in result.error


async def test_a_missing_file_is_refused(project):
    result = await tool("read_image").execute(path="nope.png")
    assert result.status is ToolResultStatus.ERROR
    assert "File not found" in result.error


async def test_reading_outside_the_project_is_refused(project):
    result = await tool("read_image").execute(path="../escape.png")
    assert result.status is ToolResultStatus.ERROR
    assert "escape" in result.error


async def test_an_oversized_source_file_is_refused(project, monkeypatch):
    """The cap bounds memory: the file is decoded in full in order to be resized."""
    from tonyagent.tools import file_tools

    make_image(project / "shot.png", size=(200, 200))
    monkeypatch.setattr(file_tools, "MAX_SOURCE_BYTES", 10)

    result = await tool("read_image").execute(path="shot.png")

    assert result.status is ToolResultStatus.ERROR
    assert "limit" in result.error
    assert result.images == []


async def test_reading_an_image_reports_no_file_change(project):
    """A read is not an edit, so it must not put a badge on the Files tree."""
    make_image(project / "shot.png")

    result = await tool("read_image").execute(path="shot.png")

    assert not [a for a in result.artifacts if a["type"] == "file_change"]
    assert [a for a in result.artifacts if a["type"] == "image"]


# --- web_fetch: the shared guard --------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, text="page body"):
        self.status_code = status_code
        self.text = text
        self.headers = {}


class _FakeClient:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self.urls.append(url)
        if self._raises is not None:
            raise self._raises
        return self._response


@pytest.fixture
def fake_http(monkeypatch):
    """Install a stub httpx, so no test in here touches the network."""
    import httpx as real_httpx

    from tonyagent.tools import network_tools

    def install(response=None, raises=None) -> _FakeClient:
        client = _FakeClient(response, raises)
        monkeypatch.setattr(
            network_tools,
            "httpx",
            SimpleNamespace(
                AsyncClient=lambda *a, **k: client,
                TimeoutException=real_httpx.TimeoutException,
            ),
        )
        return client

    return install


async def test_a_page_comes_back_as_text(project, fake_http):
    client = fake_http(response=_FakeResponse(200, "the docs say so"))

    result = await tool("web_fetch").execute(url="https://example.com/docs")

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert "the docs say so" in result.output
    assert "200" in result.output
    assert client.urls == ["https://example.com/docs"]


async def test_an_error_status_is_a_failure(project, fake_http):
    fake_http(response=_FakeResponse(404, "not found"))

    result = await tool("web_fetch").execute(url="https://example.com/missing")

    assert result.status is ToolResultStatus.ERROR
    assert "404" in result.error


async def test_a_timeout_is_reported_in_words(project, fake_http):
    import httpx as real_httpx

    fake_http(raises=real_httpx.TimeoutException("too slow"))

    result = await tool("web_fetch").execute(url="https://example.com", timeout=5)

    assert result.status is ToolResultStatus.ERROR
    assert "timed out" in result.error
    assert "5" in result.error


async def test_a_non_http_scheme_is_refused(project, fake_http):
    client = fake_http(response=_FakeResponse())

    result = await tool("web_fetch").execute(url="file:///etc/passwd")

    assert result.status is ToolResultStatus.ERROR
    assert "http://" in result.error
    assert client.urls == [], "a non-HTTP URL was still fetched"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/admin",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
    ],
)
async def test_internal_addresses_are_blocked(project, fake_http, url, monkeypatch):
    from tonyagent.config.settings import settings

    monkeypatch.setattr(settings.tools, "allow_internal_http", False)
    client = fake_http(response=_FakeResponse())

    result = await tool("web_fetch").execute(url=url)

    assert result.status is ToolResultStatus.ERROR
    assert "allow_internal_http" in result.error, (
        "the refusal does not name the setting that opens it"
    )
    assert client.urls == [], "an internal address was fetched anyway"


async def test_both_network_tools_refuse_an_internal_host_identically(
    project, fake_http, monkeypatch
):
    """The point of one shared guard: one refusal, not two similar ones.

    ``runtime_access`` exists because two copies of one condition drifted and
    told the user two different things about the same cause. This is the same
    hazard, so it is pinned the same way -- by comparing the two messages rather
    than by checking each one separately.
    """
    from tonyagent.config.settings import settings

    monkeypatch.setattr(settings.tools, "allow_internal_http", False)
    fake_http(response=_FakeResponse())

    via_fetch = await tool("web_fetch").execute(url="http://127.0.0.1/")
    via_request = await tool("http_request").execute(url="http://127.0.0.1/")

    assert via_fetch.status is ToolResultStatus.ERROR
    assert via_request.status is ToolResultStatus.ERROR
    assert via_fetch.error == via_request.error, (
        "the two network tools describe the same refusal differently:\n"
        f"  web_fetch:    {via_fetch.error}\n"
        f"  http_request: {via_request.error}"
    )


async def test_the_internal_opt_in_lets_it_through(project, fake_http, monkeypatch):
    from tonyagent.config.settings import settings

    monkeypatch.setattr(settings.tools, "allow_internal_http", True)
    client = fake_http(response=_FakeResponse(200, "local page"))

    result = await tool("web_fetch").execute(url="http://127.0.0.1/")

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert client.urls == ["http://127.0.0.1/"]


async def test_a_huge_page_is_truncated_and_says_so(project, fake_http, monkeypatch):
    from tonyagent.config.settings import settings

    monkeypatch.setattr(settings.tools, "max_output_size", 50)
    fake_http(response=_FakeResponse(200, "x" * 500))

    result = await tool("web_fetch").execute(url="https://example.com/big")

    assert result.status is ToolResultStatus.SUCCESS
    assert "truncated" in result.output, (
        "half a page was returned as though it were the whole thing"
    )


# --- the folder_required flag -------------------------------------------------


async def test_web_fetch_needs_no_project_folder(no_folder, fake_http):
    """Fetching a URL neither reads nor writes the workspace.

    Asserted through the orchestrator, which is the layer that used to
    special-case this by tool name, so a regression here is a call refused with
    "No project folder selected" rather than anything to do with the network.
    """
    from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator

    fake_http(response=_FakeResponse(200, "fine"))

    result = await ToolOrchestrator().execute_tool_async(
        ToolCall(id="w1", name="web_fetch", arguments={"url": "https://example.com"})
    )

    assert "No project folder selected" not in (result.error or "")


async def test_a_file_tool_still_needs_a_project_folder(no_folder):
    """The flag must not have exempted everything."""
    from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator

    result = await ToolOrchestrator().execute_tool_async(
        ToolCall(id="r1", name="read", arguments={"path": "x.py"})
    )

    assert result.status is ToolResultStatus.ERROR
    assert "No project folder selected" in result.error
