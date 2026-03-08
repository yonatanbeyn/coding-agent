"""OpenAI-compatible LLM client.

Works with: OpenAI, Groq, Together AI, Ollama, LM Studio, vLLM, OpenRouter,
or any provider that implements the /v1/chat/completions endpoint.
"""

from typing import Iterator

from openai import OpenAI

from .base import LLMClient, LLMResponse, ToolCall, ToolDef


def _to_openai_tool(t: ToolDef) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        },
    }


class OpenAIClient(LLMClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
        base_url: str | None = None,
    ):
        self.model = model
        self.client = OpenAI(api_key=api_key or "ollama", base_url=base_url)

    def complete(
        self,
        messages: list[dict],
        tools: list[ToolDef],
        system: str,
        max_tokens: int,
    ) -> LLMResponse:
        full_messages = [{"role": "system", "content": system}] + messages

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": full_messages,
        }
        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        content_text = msg.content or ""
        tool_calls: list[ToolCall] = []

        if msg.tool_calls:
            import json
            for tc in msg.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments or "{}"),
                    )
                )

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=resp.choices[0].finish_reason or "stop",
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[ToolDef],
        system: str,
        max_tokens: int,
    ) -> Iterator[str]:
        full_messages = [{"role": "system", "content": system}] + messages

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": full_messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content


def build_openai_messages(history: list[dict]) -> list[dict]:
    """Convert internal history to OpenAI API format."""
    import json
    messages = []
    for msg in history:
        role = msg["role"]
        if role == "user":
            messages.append({"role": "user", "content": msg["content"]})
        elif role == "assistant":
            out: dict = {"role": "assistant", "content": msg.get("content") or ""}
            if msg.get("tool_calls"):
                out["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in msg["tool_calls"]
                ]
            messages.append(out)
        elif role == "tool":
            for tr in msg.get("tool_results", []):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "content": tr["content"],
                })
    return messages