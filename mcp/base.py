"""Base types shared across all MCP tools."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolKind(str, Enum):
    READ = "read"
    ACTION = "action"


@dataclass(frozen=True)
class ToolResult:
    tool: str
    kind: ToolKind
    data: Any
    source_reference: str
    fetched_at: str  # ISO8601


@dataclass(frozen=True)
class ActionContext:
    """Required for every ACTION tool call. MCP rejects missing/invalid IDs."""
    policy_decision_id: str
    incident_id: str
    trace_id: str


class MCPError(Exception):
    """Base MCP error."""


class MCPAuthorizationError(MCPError):
    """ACTION called without valid policy_decision_id."""


class MCPConnectionError(MCPError):
    """Cannot reach the underlying infrastructure source."""


class MCPTimeoutError(MCPError):
    """Request to infrastructure source timed out."""
