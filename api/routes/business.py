"""GET /business/metrics — số liệu nghiệp vụ ERPNext (khách hàng, dự án, thanh
toán nhà thầu...) đọc qua Prometheus (business-metrics-exporter), dùng cho bot
NL Q&A.

LƯU Ý: "tồn kho" (stock/inventory) CHƯA có trong business-metrics-exporter
(xem cluster-bootstrap/business-metrics-exporter/templates/configmap.yaml —
chỉ export erpnext_customers_total/projects_total/tasks_overdue_total/
contractor_payment_requests_total). Cần mở rộng exporter nếu muốn số liệu này.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_prometheus_tools
from mcp.base import MCPError

router = APIRouter(prefix="/business", tags=["business"])

# Metric name → PromQL instant-query. Khớp đúng tên trong
# cluster-bootstrap/business-metrics-exporter/templates/configmap.yaml.
_QUERIES = {
    "customers_active": 'erpnext_customers_total{disabled="0"}',
    "customers_disabled": 'erpnext_customers_total{disabled="1"}',
    "projects_by_status": "erpnext_projects_total",
    "tasks_overdue": "erpnext_tasks_overdue_total",
    "contractor_payment_requests_by_state": "erpnext_contractor_payment_requests_total",
}


@router.get("/metrics")
async def business_metrics(tools=Depends(get_prometheus_tools)):
    out: dict[str, object] = {}
    for name, query in _QUERIES.items():
        try:
            result = await tools.prometheus_query(query)
            samples = result.data.get("data", {}).get("result", [])
            out[name] = [
                {"labels": s.get("metric", {}), "value": s.get("value", [None, None])[1]}
                for s in samples
            ]
        except MCPError as e:
            out[name] = {"error": str(e)}
    out["_note"] = (
        "Chưa có dữ liệu tồn kho (stock/inventory) — business-metrics-exporter "
        "chưa export metric này."
    )
    return out


@router.get("/query")
async def business_query(promql: str, tools=Depends(get_prometheus_tools)):
    """Query PromQL tuỳ ý (chỉ đọc) — dùng khi bot cần metric ngoài danh sách cố định."""
    try:
        result = await tools.prometheus_query(promql)
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result.data
