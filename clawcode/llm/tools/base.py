"""Base tool system for LLM agent.

This module provides the base classes and interfaces for implementing
tools that can be called by the LLM agent.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..claw_support.iteration_budget import IterationBudget

from pydantic import BaseModel

from ..tool_call_normalize import normalize_tool_input_dict


@dataclass
class ToolInfo:
    """Metadata about a tool.

    Attributes:
        name: Unique tool identifier
        description: Human-readable description
        parameters: JSON Schema for parameters
        required: List of required parameter names
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format.

        Returns:
            Dictionary representation
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
        }


@dataclass
class ToolCall:
    """Represents a tool call from the LLM.

    Attributes:
        id: Unique call identifier
        name: Name of the tool to call
        input: Tool input parameters (can be JSON string or dict)
    """

    id: str
    name: str
    input: str | dict[str, Any]
    _cached_input_dict: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def get_input_dict(self) -> dict[str, Any]:
        """Get input as dictionary (result is cached after first call).

        Returns:
            Input parameters as dictionary
        """
        if self._cached_input_dict is not None:
            return self._cached_input_dict
        if isinstance(self.input, dict):
            result = normalize_tool_input_dict(self.input, tool_name=self.name)
        else:
            parsed: Any = None
            try:
                parsed = json.loads(self.input)
            except json.JSONDecodeError:
                # Fallback: try ast.literal_eval for single-quoted Python dicts
                try:
                    import ast
                    parsed = ast.literal_eval(self.input)
                except Exception:
                    result = {"raw": self.input}
                    self._cached_input_dict = result
                    return result
            if isinstance(parsed, dict):
                result = normalize_tool_input_dict(parsed, tool_name=self.name)
            else:
                result = parsed
        self._cached_input_dict = result
        return result


@dataclass
class ToolResponse:
    """Response from tool execution.

    Attributes:
        content: The response content
        metadata: Optional metadata (as JSON string)
        is_error: Whether the response is an error
    """

    content: str
    metadata: str | None = None
    is_error: bool = False

    @classmethod
    def text(cls, content: str) -> "ToolResponse":
        """Create a text response.

        Args:
            content: Response content

        Returns:
            ToolResponse instance
        """
        return cls(content=content)

    @classmethod
    def error(cls, content: str) -> "ToolResponse":
        """Create an error response.

        Args:
            content: Error message

        Returns:
            ToolResponse instance with is_error=True
        """
        return cls(content=content, is_error=True)

    def with_metadata(self, metadata: Any) -> "ToolResponse":
        """Add metadata to the response.

        Args:
            metadata: Metadata object (will be JSON serialized)

        Returns:
            Self with metadata added
        """
        self.metadata = json.dumps(metadata)
        return self


class ToolContext:
    """Execution context for tool calls.

    Provides access to services and information during tool execution.
    """

    def __init__(
        self,
        session_id: str,
        message_id: str,
        working_directory: str,
        permission_service: Any = None,
        plan_mode: bool = False,
        iteration_budget: "IterationBudget | None" = None,
    ) -> None:
        """Initialize the tool context.

        Args:
            session_id: Current session ID
            message_id: Current message ID
            working_directory: Current working directory
            permission_service: Permission service (optional)
            iteration_budget: When set (e.g. Claw mode), nested Agent runs share this cap.
        """
        self.session_id = session_id
        self.message_id = message_id
        self.working_directory = working_directory
        self.permission_service = permission_service
        self.plan_mode = plan_mode
        self.iteration_budget = iteration_budget


class BaseTool(ABC):
    """Abstract base class for all tools.

    Tools must implement this interface to be used by the agent.
    """

    @abstractmethod
    def info(self) -> ToolInfo:
        """Get tool metadata.

        Returns:
            ToolInfo instance
        """
        pass

    @abstractmethod
    async def run(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        """Execute the tool.

        Args:
            call: The tool call details
            context: The execution context

        Returns:
            ToolResponse instance

        Raises:
            Exception: If the tool execution fails
        """
        pass

    @property
    def requires_permission(self) -> bool:
        """Check if tool requires permission.

        Returns:
            True if tool requires user permission
        """
        return True

    @property
    def is_dangerous(self) -> bool:
        """Check if tool is potentially dangerous.

        Dangerous tools are things like file writes, command execution, etc.

        Returns:
            True if tool is potentially dangerous
        """
        return False


class ToolError(Exception):
    """Base exception for tool errors."""

    def __init__(self, message: str, tool: str | None = None) -> None:
        """Initialize the error.

        Args:
            message: Error message
            tool: Tool name
        """
        self.tool = tool
        super().__init__(message)


class ToolPermissionError(ToolError):
    """Raised when tool permission is denied."""

    pass


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""

    pass


# Tool registry

_tool_registry: dict[str, type[BaseTool]] = {}


def register_tool(tool_class: type[BaseTool]) -> type[BaseTool]:
    """Decorator to register a tool class.

    Args:
        tool_class: Tool class to register

    Returns:
        The tool class (unchanged)
    """
    # Create instance to get info
    instance = tool_class()
    info = instance.info()
    _tool_registry[info.name] = tool_class
    return tool_class


def get_tool(name: str) -> BaseTool | None:
    """Get a tool instance by name.

    Args:
        name: Tool name

    Returns:
        Tool instance or None if not found
    """
    tool_class = _tool_registry.get(name)
    if tool_class:
        return tool_class()
    return None


def list_tools() -> list[ToolInfo]:
    """List all registered tools.

    Returns:
        List of tool info
    """
    return [
        tool_class().info() for tool_class in _tool_registry.values()
    ]


# Helper function for creating tool schemas

def create_tool_schema(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Create a tool schema dictionary.

    Args:
        name: Tool name
        description: Tool description
        parameters: JSON Schema for parameters
        required: List of required parameter names

    Returns:
        Tool schema dictionary
    """
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": parameters,
            "required": required or [],
        },
    }


# Common parameter schemas

def string_param(description: str, **kwargs: Any) -> dict[str, Any]:
    """Create a string parameter schema.

    Args:
        description: Parameter description
        **kwargs: Additional schema properties

    Returns:
        Parameter schema
    """
    return {
        "type": "string",
        "description": description,
        **kwargs,
    }


def integer_param(description: str, **kwargs: Any) -> dict[str, Any]:
    """Create an integer parameter schema.

    Args:
        description: Parameter description
        **kwargs: Additional schema properties

    Returns:
        Parameter schema
    """
    return {
        "type": "integer",
        "description": description,
        **kwargs,
    }


def array_param(
    description: str, item_type: str = "string", **kwargs: Any
) -> dict[str, Any]:
    """Create an array parameter schema.

    Args:
        description: Parameter description
        item_type: Type of array items
        **kwargs: Additional schema properties

    Returns:
        Parameter schema
    """
    return {
        "type": "array",
        "description": description,
        "items": {"type": item_type},
        **kwargs,
    }
