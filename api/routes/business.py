"""GET /business/metrics — số liệu nghiệp vụ ERPNext (khách hàng, dự án, task
quá hạn, thanh toán nhà thầu, tồn kho, items, đơn bán/mua hàng) đọc qua
Prometheus (business-metrics-exporter), dùng cho bot NL Q&A.
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
    "stock_qty_by_warehouse": "erpnext_stock_qty_total",
    "stock_reserved_qty_by_warehouse": "erpnext_stock_reserved_qty_total",
    "items_by_type": "erpnext_items_total",
    "sales_orders_by_status": "erpnext_sales_orders_total",
    "sales_orders_value_by_status": "erpnext_sales_orders_value_total",
    "purchase_orders_by_status": "erpnext_purchase_orders_total",
    "purchase_orders_value_by_status": "erpnext_purchase_orders_value_total",
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
    return out


@router.get("/query")
async def business_query(promql: str, tools=Depends(get_prometheus_tools)):
    """Query PromQL tuỳ ý (chỉ đọc) — dùng khi bot cần metric ngoài danh sách cố định."""
    try:
        result = await tools.prometheus_query(promql)
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result.data
