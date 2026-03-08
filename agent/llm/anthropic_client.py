"""Anthropic (Claude) LLM client."""

from typing import Iterator

import anthropic

from .base import LLMClient, LLMResponse, ToolCall, ToolDef


def _to_anthropic_tool(t: ToolDef) -> dict:
    return {
        "name": t.name,
        "description": t.description,
        "input_schema": t.parameters,
    }


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6"):
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        messages: list[dict],
        tools: list[ToolDef],
        system: str,
        max_tokens: int,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [_to_anthropic_tool(t) for t in tools]

        resp = self.client.messages.create(**kwargs)

        content_text = ""
        tool_calls: list[ToolCall] = []

        for block in resp.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "end_turn",
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[ToolDef],
        system: str,
        max_tokens: int,
    ) -> Iterator[str]:
        """Stream text; returns full response via complete() after."""
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [_to_anthropic_tool(t) for t in tools]

        with self.client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text

    def complete_after_stream(
        self,
        messages: list[dict],
        tools: list[ToolDef],
        system: str,
        max_tokens: int,
    ) -> LLMResponse:
        """Stream to console, then return the final response object."""
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [_to_anthropic_tool(t) for t in tools]

        with self.client.messages.stream(**kwargs) as stream:
            # yield text while streaming
            for _ in stream.text_stream:
                pass
            final = stream.get_final_message()

        content_text = ""
        tool_calls: list[ToolCall] = []

        for block in final.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=final.stop_reason or "end_turn",
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )


def build_anthropic_messages(history: list[dict]) -> list[dict]:
    """Convert internal message history to Anthropic API format."""
    messages = []
    for msg in history:
        role = msg["role"]
        if role == "user":
            messages.append({"role": "user", "content": msg["content"]})
        elif role == "assistant":
            content = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            for tc in msg.get("tool_calls", []):
                content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["arguments"],
                })
            messages.append({"role": "assistant", "content": content})
        elif role == "tool":
            # Anthropic expects tool results in a user message
            tool_results = msg.get("tool_results", [])
            content = []
            for tr in tool_results:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": tr["tool_call_id"],
                    "content": tr["content"],
                    "is_error": tr.get("is_error", False),
                })
            messages.append({"role": "user", "content": content})
    return messages