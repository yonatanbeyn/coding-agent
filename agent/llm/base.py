"""Base types and abstract interface for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class ToolDef:
    """Universal tool definition — converted per-provider as needed."""
    name: str
    description: str
    parameters: dict  # JSON Schema object
    fn: Any = None    # callable — set by registry


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """Result of executing a tool."""
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "tool"
    content: Any  # str or list of content blocks
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        tools: list[ToolDef],
        system: str,
        max_tokens: int,
    ) -> LLMResponse:
        """Send messages to the LLM and return a response."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[dict],
        tools: list[ToolDef],
        system: str,
        max_tokens: int,
    ) -> Iterator[str]:
        """Stream text tokens; tool calls are handled after stream ends."""
        ...