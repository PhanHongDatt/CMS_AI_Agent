"""Prometheus read-only MCP tools."""

from datetime import datetime, timezone
from typing import Any

import httpx

from mcp.base import MCPConnectionError, MCPTimeoutError, ToolKind, ToolResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PrometheusReadonlyTools:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def prometheus_query(self, query: str, time: str | None = None) -> ToolResult:
        """Instant query against Prometheus."""
        params: dict[str, str] = {"query": query}
        if time:
            params["time"] = time
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base}/api/v1/query", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            raise MCPTimeoutError(f"Prometheus query timed out: {e}") from e
        except httpx.HTTPError as e:
            raise MCPConnectionError(f"Prometheus query failed: {e}") from e

        return ToolResult(
            tool="prometheus_query",
            kind=ToolKind.READ,
            data=data,
            source_reference=f"{self._base}/api/v1/query?query={query}",
            fetched_at=_now(),
        )

    async def prometheus_query_range(
        self, query: str, start: str, end: str, step: str = "60s"
    ) -> ToolResult:
        params = {"query": query, "start": start, "end": end, "step": step}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base}/api/v1/query_range", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            raise MCPTimeoutError(f"Prometheus range query timed out: {e}") from e
        except httpx.HTTPError as e:
            raise MCPConnectionError(f"Prometheus range query failed: {e}") from e

        return ToolResult(
            tool="prometheus_query_range",
            kind=ToolKind.READ,
            data=data,
            source_reference=f"{self._base}/api/v1/query_range",
            fetched_at=_now(),
        )
