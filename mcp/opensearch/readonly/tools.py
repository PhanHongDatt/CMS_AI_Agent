"""OpenSearch read-only MCP tools."""

from datetime import datetime, timezone
from typing import Any

import httpx

from mcp.base import MCPConnectionError, MCPTimeoutError, ToolKind, ToolResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenSearchReadonlyTools:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def opensearch_query(
        self,
        index: str,
        query: dict[str, Any],
        size: int = 100,
    ) -> ToolResult:
        """Execute a search query against OpenSearch."""
        body = {"query": query, "size": size}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base}/{index}/_search",
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            raise MCPTimeoutError(f"OpenSearch query timed out: {e}") from e
        except httpx.HTTPError as e:
            raise MCPConnectionError(f"OpenSearch query failed: {e}") from e

        return ToolResult(
            tool="opensearch_query",
            kind=ToolKind.READ,
            data=data,
            source_reference=f"{self._base}/{index}/_search",
            fetched_at=_now(),
        )

    async def opensearch_get_log_errors(
        self,
        index: str,
        minutes: int = 30,
        size: int = 100,
    ) -> ToolResult:
        """Fetch recent ERROR-level log entries."""
        query = {
            "bool": {
                "must": [
                    {"term": {"level": "ERROR"}},
                    {"range": {"@timestamp": {"gte": f"now-{minutes}m", "lte": "now"}}},
                ]
            }
        }
        return await self.opensearch_query(index, query, size)
