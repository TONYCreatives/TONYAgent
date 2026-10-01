"""Attachments: the model sees the file, not a mention of it.

The core had no attachment path at all -- `_h_send` read `params["text"]` and
`session.send` took a string -- so the only way to talk to the agent about a
file was to name its path and hope it owned a tool that could read it. These
cover the change that puts the bytes in the message instead.

What is asserted here, and why each is not obvious:

* **Validation is in the core.** The window is a rendering layer, not a trust
  boundary. A message is a JSON object on a pipe, and the limits are what keep
  a request inside what a provider will accept.
* **An empty body with an attachment is a message.** "What is in this
  screenshot?" has no words in it, and refusing it would make the obvious use
  of the feature the one thing it cannot do.
* **Token estimation counts text.** `estimate_tokens` was
  `len(m.content or "")`, which counts characters for a string and *parts* for
  a list -- so a 4000-character document attached as three parts estimated at
  zero tokens. Nothing crashed; the budget just stopped counting.
* **A refused file is refused with a reason.** "This is a PDF" and "something
  went wrong" are different problems and only one of them has a next step.
"""

import asyncio
import base64
import io
import json

import pytest

from tonyagent.core.attachments import (
    MAX_ATTACHMENTS,
    MAX_ATTACHMENT_BYTES,
    AttachmentError,
    build_parts,
    resolve_mime,
    summarise,
    validate,
)
from tonyagent.core.events import EventBus
from tonyagent.core.session import AgentSession
from tonyagent.providers import ChatMessage
from tonyagent.providers.base import OpenAICompatibleProvider

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
GIF = base64.b64encode(b"GIF89a" + b"0" * 32).decode()


def text_attachment(name="notes.md", body="hello"):
    return {
        "name": name,
        "mime": "text/markdown",
        "data": base64.b64encode(body.encode()).decode(),
    }


def image_attachment(name="shot.png", data=PNG, mime="image/png"):
    return {"name": name, "mime": mime, "data": data}


class TestWhatIsAccepted:
    def test_a_png_is_accepted(self):
        accepted = validate([image_attachment()])
        assert len(accepted) == 1
        assert accepted[0]["kind"] == "image"
        assert accepted[0]["mime"] == "image/png"

    def test_every_vision_type_is_accepted(self):
        for mime in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            accepted = validate([image_attachment(mime=mime, data=GIF)])
            assert accepted[0]["mime"] == mime

    def test_a_text_file_is_accepted(self):
        accepted = validate([text_attachment()])
        assert accepted[0]["kind"] == "text"
        assert accepted[0]["text"] == "hello"

    def test_several_files_at_once_are_accepted(self):
        accepted = validate([image_attachment(), text_attachment()])
        assert [a["kind"] for a in accepted] == ["image", "text"]

    def test_no_attachments_is_no_attachments(self):
        assert validate(None) == []
        assert validate([]) == []


class TestWhatIsRefused:
    def test_a_pdf_is_refused_with_a_next_step(self):
        # OpenRouter's chat completions does not take a document part, so a
        # PDF would have to become text -- and a PDF made of text is usually not
        # what someone attaching it wants. Saying so beats a lossy conversion
        # the user cannot see.
        with pytest.raises(AttachmentError) as caught:
            validate([{"name": "spec.pdf", "mime": "application/pdf", "data": "JVBER"}])
        message = str(caught.value)
        assert "PDF" in message
        assert "screenshot" in message

    def test_a_pdf_is_refused_even_with_no_declared_type(self):
        # A browser on Windows often reports no type at all, so the extension
        # is what the refusal has to go on.
        with pytest.raises(AttachmentError) as caught:
            validate([{"name": "spec.pdf", "data": "JVBER"}])
        assert "PDF" in str(caught.value)

    def test_a_binary_type_is_refused_with_its_type_named(self):
        with pytest.raises(AttachmentError) as caught:
            validate([{"name": "app.exe", "mime": "application/x-msdownload", "data": "AA"}])
        assert "application/x-msdownload" in str(caught.value)

    def test_a_file_with_no_readable_type_says_what_will_work(self):
        with pytest.raises(AttachmentError) as caught:
            validate([{"name": "mystery", "data": "AA"}])
        message = str(caught.value)
        assert "image" in message and "text" in message

    def test_an_unsupported_image_type_is_named(self):
        # A .tiff is an image the user would reasonably attach, and it is not
        # one a model reads. Saying "TIFF" beats a generic refusal.
        with pytest.raises(AttachmentError) as caught:
            validate([image_attachment(mime="image/tiff", data=GIF)])
        assert "tiff" in str(caught.value).lower()

    def test_too_many_files_is_refused_by_count(self):
        many = [image_attachment(name=f"s{i}.png") for i in range(MAX_ATTACHMENTS + 1)]
        with pytest.raises(AttachmentError) as caught:
            validate(many)
        assert str(MAX_ATTACHMENTS) in str(caught.value)

    def test_an_oversized_image_is_refused_with_its_size(self):
        big = base64.b64encode(b"\x89PNG" + b"0" * (MAX_ATTACHMENT_BYTES + 16)).decode()
        with pytest.raises(AttachmentError) as caught:
            validate([image_attachment(data=big)])
        message = str(caught.value)
        assert "limit" in message
        assert "KB" in message

    def test_a_corrupt_image_is_refused_as_corrupt(self):
        # Not as a crash and not as "unsupported type": the file is a PNG that
        # did not survive base64, and those have different fixes.
        with pytest.raises(AttachmentError) as caught:
            validate([image_attachment(data="not base64 at all !!")])
        assert "corrupt" in str(caught.value).lower()

    def test_an_attachment_with_no_content_is_refused(self):
        with pytest.raises(AttachmentError):
            validate([{"name": "empty.png", "mime": "image/png", "data": ""}])

    def test_a_non_list_is_refused(self):
        with pytest.raises(AttachmentError):
            validate({"name": "one.png"})

    def test_an_entry_that_is_not_an_object_is_refused(self):
        with pytest.raises(AttachmentError):
            validate(["just a string"])

    def test_a_huge_text_file_is_truncated_rather_than_refused(self):
        # A 2MB log is an accident, not a question, and sending it whole costs
        # a fortune and answers nothing. Truncating keeps the part that matters.
        accepted = validate([text_attachment(body="x" * 300_000)])
        assert len(accepted[0]["text"]) == 100_000


class TestMimeResolution:
    def test_a_declared_type_wins(self):
        assert resolve_mime("image/PNG", "a.bin") == "image/png"

    def test_a_charset_parameter_is_stripped(self):
        assert resolve_mime("text/plain; charset=utf-8", "a.txt") == "text/plain"

    def test_an_empty_type_falls_back_to_the_extension(self):
        # On Windows a browser reports "" for a .py file often enough that
        # refusing on an empty type would reject most of what a developer
        # would want to attach.
        assert resolve_mime("", "script.py") == "text/x-python"
        assert resolve_mime(None, "notes.md") == "text/markdown"

    def test_an_unknown_extension_stays_unknown(self):
        assert resolve_mime("", "thing.qqq") == ""


class TestTheContentParts:
    def test_the_typed_text_comes_first(self):
        # The text is the question and the files are its evidence. A message
        # that opens with a wall of base64 has put the answer after the payload.
        parts = build_parts(validate([image_attachment()]), "what is this?")
        assert parts[0] == {"type": "text", "text": "what is this?"}
        assert parts[1]["type"] == "image_url"

    def test_an_image_becomes_a_data_url(self):
        parts = build_parts(validate([image_attachment()]), "hi")
        url = parts[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        assert url.endswith(PNG)

    def test_a_text_file_is_named_inside_its_part(self):
        # The model is reading this and has to know which file it is looking
        # at when several are attached.
        parts = build_parts(validate([text_attachment("report.md", "42")]), "")
        assert "report.md" in parts[0]["text"]
        assert "42" in parts[0]["text"]

    def test_an_attachment_with_no_text_still_builds_parts(self):
        parts = build_parts(validate([image_attachment()]), "")
        assert len(parts) == 1
        assert parts[0]["type"] == "image_url"

    def test_a_summary_names_what_was_attached(self):
        # A bubble with no words in it looks like nothing was sent, which is
        # what a reopened conversation would show.
        assert "shot.png" in summarise(validate([image_attachment()]))
        assert "2 files" in summarise(validate([image_attachment(), text_attachment()]))
        assert summarise([]) == ""


class TestTokenEstimation:
    def _provider(self):
        class _P(OpenAICompatibleProvider):
            key_prefix = "k-"
            name = "p"
            models: list = []

        return _P(api_key="k")

    def test_a_plain_string_still_counts_characters(self):
        provider = self._provider()
        messages = [ChatMessage(role="user", content="x" * 400)]
        assert provider.estimate_tokens(messages) == 100

    def test_text_parts_are_counted(self):
        # The bug this change would have introduced: `len(m.content or "")` on
        # a list returns the number of parts, so this estimated at 0 and the
        # budget silently stopped counting.
        provider = self._provider()
        messages = [
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "x" * 400},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            )
        ]
        assert provider.estimate_tokens(messages) == 100

    def test_an_image_alone_does_not_add_tokens(self):
        # Counting base64 characters would report a 40KB image as ten thousand
        # tokens of prose.
        provider = self._provider()
        messages = [
            ChatMessage(
                role="user",
                content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 40000}}],
            )
        ]
        assert provider.estimate_tokens(messages) == 0

    def test_a_message_with_no_content_costs_nothing(self):
        provider = self._provider()
        assert provider.estimate_tokens([ChatMessage(role="assistant")]) == 0


class TestTheWire:
    """The message has to reach the provider intact, which is the whole point."""

    def test_parts_pass_through_the_dialect_unchanged(self):
        from tonyagent.api.dialects import Dialect

        message = ChatMessage(
            role="user",
            content=[
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        )
        payload = Dialect().build_request("m", [message.to_dict()])
        # `build_request` passes messages verbatim, which is why this feature
        # needed no dialect change. Asserted so a future "normalisation" pass
        # cannot quietly break it.
        assert payload["messages"][0]["content"] == message.content

    def test_a_plain_message_is_still_a_plain_string(self):
        # Not a one-part list. A special case for the common path would be a
        # special case in every reader of the history.
        assert ChatMessage(role="user", content="hi").to_dict()["content"] == "hi"


class TestTheSendRpc:
    def _drive(self, requests, session=None):
        from tonyagent.headless.server import StdioServer

        if session is None:
            session = AgentSession(bus=EventBus())
            session.provider = object()
            session.model = "stub"
        stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
        stdout = io.StringIO()
        asyncio.run(StdioServer(session, stdin, stdout).serve())
        return [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]

    def test_a_text_only_send_is_unchanged(self):
        frames = self._drive([{"id": 1, "method": "send", "params": {"text": "hi"}}])
        assert "result" in frames[0]

    def test_an_attachment_is_accepted(self):
        frames = self._drive([
            {
                "id": 1,
                "method": "send",
                "params": {"text": "what is this?", "attachments": [image_attachment()]},
            }
        ])
        assert "result" in frames[0], frames[0]

    def test_a_message_with_only_an_attachment_is_a_message(self):
        # "What is in this screenshot?" has no words in it. Refusing it would
        # make the obvious use of the feature the one thing it cannot do.
        frames = self._drive([
            {"id": 1, "method": "send", "params": {"text": "", "attachments": [image_attachment()]}}
        ])
        assert "result" in frames[0], frames[0]

    def test_a_refused_attachment_is_an_error_the_window_can_show(self):
        frames = self._drive([
            {
                "id": 1,
                "method": "send",
                "params": {"text": "hi", "attachments": [{"name": "a.pdf", "data": "JVBER"}]},
            }
        ])
        assert "error" in frames[0]
        assert "PDF" in frames[0]["error"]["message"]

    def test_a_oversized_attachment_never_reaches_the_session(self):
        # The limit is enforced before the turn starts, not after -- otherwise
        # the request is already in flight and the cost is already incurred.
        session = AgentSession(bus=EventBus())
        session.provider = object()
        session.model = "stub"
        big = base64.b64encode(b"\x89PNG" + b"0" * (MAX_ATTACHMENT_BYTES + 16)).decode()
        frames = self._drive(
            [{"id": 1, "method": "send", "params": {"text": "", "attachments": [image_attachment(data=big)]}}],
            session=session,
        )
        assert "error" in frames[0]
        assert session.messages == [], "a rejected attachment was still queued"

    def test_text_must_be_a_string(self):
        frames = self._drive([{"id": 1, "method": "send", "params": {"text": 5}}])
        assert "error" in frames[0]

    def test_an_empty_message_with_no_attachments_is_still_refused(self):
        frames = self._drive([{"id": 1, "method": "send", "params": {"text": "   "}}])
        assert "empty message" in frames[0]["error"]["message"]


class TestTheSession:
    """
    ``send`` schedules the turn on the running loop, so these run inside one.
    """

    def _session(self):
        session = AgentSession(bus=EventBus())
        session.provider = object()
        session.model = "stub"
        return session

    async def test_a_plain_send_stores_a_string(self):
        session = self._session()
        assert session.send("hello")
        assert session.messages[0].content == "hello"

    async def test_a_send_with_files_stores_parts(self):
        session = self._session()
        session.send("look", validate([image_attachment()]))
        content = session.messages[0].content
        assert isinstance(content, list)
        assert content[0]["text"] == "look"

    async def test_a_file_with_no_words_still_starts_a_turn(self):
        # What is in this screenshot has no words in it. Refusing it would
        # make the obvious use of the feature the one thing it cannot do.
        session = self._session()
        assert session.send("", validate([image_attachment()])) != ""

    async def test_nothing_at_all_is_refused(self):
        session = self._session()
        assert session.send("") == ""
        assert session.send("", []) == ""
        assert session.messages == []

