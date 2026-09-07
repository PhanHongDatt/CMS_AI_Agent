"""Gate G2: Prometheus MCP read-only contract tests."""

import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from mcp.base import MCPConnectionError, MCPTimeoutError, ToolKind
from mcp.prometheus.readonly.tools import PrometheusReadonlyTools


def _prometheus_response(result_type: str = "vector") -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": result_type,
            "result": [{"metric": {"__name__": "up"}, "value": [1722000000, "1"]}],
        },
    }


class TestPrometheusReadonly:
    @pytest.mark.asyncio
    async def test_query_returns_tool_result(self, respx_mock):
        respx_mock.get("http://prometheus:9090/api/v1/query").mock(
            return_value=httpx.Response(200, json=_prometheus_response())
        )
        tools = PrometheusReadonlyTools("http://prometheus:9090")
        result = await tools.prometheus_query("up")
        assert result.kind == ToolKind.READ
        assert result.data["status"] == "success"

    @pytest.mark.asyncio
    async def test_query_connection_error(self, respx_mock):
        respx_mock.get("http://prometheus:9090/api/v1/query").mock(
            side_effect=httpx.ConnectError("refused")
        )
        tools = PrometheusReadonlyTools("http://prometheus:9090")
        with pytest.raises(MCPConnectionError):
            await tools.prometheus_query("up")

    @pytest.mark.asyncio
    async def test_query_timeout_error(self, respx_mock):
        respx_mock.get("http://prometheus:9090/api/v1/query").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        tools = PrometheusReadonlyTools("http://prometheus:9090")
        with pytest.raises(MCPTimeoutError):
            await tools.prometheus_query("up")

    @pytest.mark.asyncio
    async def test_source_reference_contains_query(self, respx_mock):
        respx_mock.get("http://prometheus:9090/api/v1/query").mock(
            return_value=httpx.Response(200, json=_prometheus_response())
        )
        tools = PrometheusReadonlyTools("http://prometheus:9090")
        result = await tools.prometheus_query("container_cpu_usage")
        assert "container_cpu_usage" in result.source_reference
