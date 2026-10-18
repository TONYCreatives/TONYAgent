"""Responses wire format: request building, stream parsing, fallback routing."""

import json

from tonyagent.api.client import (
    RESPONSES_DIRECT_PREFIXES,
    LLMClient,
    _is_protocol_mismatch,
)
from tonyagent.api.dialects import (
    ResponsesDialect,
    messages_to_responses_input,
    responses_current_tool_calls,
    responses_output,
    responses_tools,
)
from tonyagent.api.errors import LLMError


def test_chat_tools_flatten_to_responses_tools():
    chat_tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]
    out = responses_tools(chat_tools)
    assert out == [
        {
            "type": "function",
            "name": "read",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
    assert responses_tools(None) is None
    assert responses_tools([]) is None


def test_history_maps_to_responses_input():
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hello."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "read", "arguments": '{"path": "a"}'}},
            ],
        },
        {"role": "tool", "content": '{"ok": true}', "tool_call_id": "c1"},
    ]
    items = messages_to_responses_input(messages)
    assert items[0] == {"role": "system", "content": "Be brief."}
    assert items[1] == {"role": "user", "content": "Hello."}
    assert items[2] == {
        "type": "function_call", "call_id": "c1", "name": "read",
        "arguments": '{"path": "a"}',
    }
    assert items[3] == {
        "type": "function_call_output", "call_id": "c1", "output": '{"ok": true}',
    }


def test_image_parts_map_to_input_image():
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]},
    ]
    items = messages_to_responses_input(messages)
    assert items == [{"role": "user", "content": [
        {"type": "input_text", "text": "What is this?"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
    ]}]


def test_build_request_targets_responses_url_and_shape():
    dialect = ResponsesDialect()
    assert dialect.url("https://opencode.ai/zen/go/v1", "m", True).endswith("/responses")
    payload = dialect.build_request(
        "muse-spark-1.3-contributor",
        [{"role": "user", "content": "Hi"}],
        [{"type": "function", "function": {"name": "read", "description": "r",
                                           "parameters": {"type": "object"}}}],
        "auto",
        stream=True,
    )
    assert payload["model"] == "muse-spark-1.3-contributor"
    assert payload["stream"] is True
    assert payload["input"] == [{"role": "user", "content": "Hi"}]
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["name"] == "read"
    assert payload["tool_choice"] == "auto"


def test_parse_completion_reads_text_and_function_calls():
    dialect = ResponsesDialect()
    result = dialect.parse_completion({
        "model": "m",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Hi there"}]},
            {"type": "function_call", "call_id": "c9", "name": "glob",
             "arguments": '{"pattern": "**/*.py"}'},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })
    assert result.content == "Hi there"
    assert result.tool_calls == [{
        "id": "c9", "type": "function",
        "function": {"name": "glob", "arguments": '{"pattern": "**/*.py"}'},
    }]
    assert result.finish_reason == "tool_calls"
    assert result.usage.total == 15


def test_stream_deltas_accumulate_text_and_tool_args():
    dialect = ResponsesDialect()
    acc: dict = {}
    text = dialect.parse_stream_event(
        "response.output_text.delta",
        json.dumps({"type": "response.output_text.delta", "delta": "Hel"}), acc)
    assert text is not None and text.content == "Hel"
    dialect.parse_stream_event(
        "response.output_item.added",
        json.dumps({"type": "response.output_item.added",
                    "item": {"type": "function_call", "id": "i1",
                             "call_id": "c1", "name": "read"}}), acc)
    dialect.parse_stream_event(
        "response.function_call_arguments.delta",
        json.dumps({"type": "response.function_call_arguments.delta",
                    "item_id": "i1", "delta": '{"path":'}), acc)
    dialect.parse_stream_event(
        "response.function_call_arguments.delta",
        json.dumps({"type": "response.function_call_arguments.delta",
                    "item_id": "i1", "delta": ' "a"}'}), acc)
    done = dialect.parse_stream_event(
        "response.completed",
        json.dumps({"type": "response.completed",
                    "response": {"model": "m",
                                 "usage": {"input_tokens": 3, "output_tokens": 7}}}), acc)
    assert done is not None and done.finish_reason == "tool_calls"
    calls = responses_current_tool_calls(acc)
    assert calls == [{
        "id": "c1", "type": "function",
        "function": {"name": "read", "arguments": '{"path": "a"}'},
    }]
    assert acc["usage"].total == 10


def test_protocol_mismatch_detected_narrowly():
    err = LLMError.from_response(
        400, '{"error": {"message": "Model does not support this protocol"}}', "opencode-go")
    assert _is_protocol_mismatch(err) is True
    other = LLMError.from_response(400, '{"error": {"message": "Bad JSON"}}', "opencode-go")
    assert _is_protocol_mismatch(other) is False
    auth = LLMError.from_response(401, "User not found", "opencode-go")
    assert _is_protocol_mismatch(auth) is False


def test_muse_spark_routes_to_responses_first():
    chat_first = LLMClient(provider="p", api_key="k" * 40, model="deepseek-v4.1-flash",
                           base_url="https://x/v1", key_prefix="")
    assert [type(d).__name__ for d in chat_first._dialect_order()] == [
        "Dialect", "ResponsesDialect"]
    spark = LLMClient(provider="p", api_key="k" * 40, model="muse-spark-1.3-contributor",
                      base_url="https://x/v1", key_prefix="")
    assert [type(d).__name__ for d in spark._dialect_order()] == [
        "ResponsesDialect", "Dialect"]
    assert any("muse-spark-" in p for p in RESPONSES_DIRECT_PREFIXES)


def test_responses_output_helper_empty():
    assert responses_output([]) == ("", None)
