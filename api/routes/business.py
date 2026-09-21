"""GET /business/metrics — số liệu nghiệp vụ ERPNext (khách hàng, dự án, task
quá hạn, thanh toán nhà thầu, tồn kho, items, đơn bán/mua hàng) đọc qua
Prometheus (business-metrics-exporter), dùng cho bot NL Q&A.

GET /business/customers, /projects, /tasks — CHI TIẾT (tên, không chỉ số
lượng). Prometheus chỉ lưu được số liệu tổng hợp (counter/gauge), KHÔNG lưu
được text như tên khách hàng — nên các endpoint này đọc THẲNG MariaDB qua
user "bizmetrics" (SELECT-only). Query CỐ ĐỊNH, whitelist — bot/LLM KHÔNG
được tự viết SQL (tránh injection/rò rỉ dữ liệu ngoài ý muốn).
"""

import asyncio

import pymysql
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_erp_db_config, get_prometheus_tools
from mcp.base import MCPError

router = APIRouter(prefix="/business", tags=["business"])


def _erp_query(config: dict, sql: str, limit: int = 20) -> list[dict]:
    conn = pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        connect_timeout=10,
        read_timeout=15,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return cur.fetchall()
    finally:
        conn.close()


@router.get("/customers")
async def business_customers(limit: int = 20, config=Depends(get_erp_db_config)):
    if config is None:
        raise HTTPException(status_code=503, detail="ERPNext DB not configured")
    try:
        rows = await asyncio.to_thread(
            _erp_query,
            config,
            "SELECT name, customer_name, disabled FROM `tabCustomer` ORDER BY creation DESC LIMIT %s",  # noqa: E501
            limit,
        )
    except pymysql.Error as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return rows


@router.get("/projects")
async def business_projects(limit: int = 20, config=Depends(get_erp_db_config)):
    if config is None:
        raise HTTPException(status_code=503, detail="ERPNext DB not configured")
    try:
        rows = await asyncio.to_thread(
            _erp_query,
            config,
            "SELECT name, project_name, status, expected_end_date FROM `tabProject` "
            "WHERE docstatus < 2 ORDER BY creation DESC LIMIT %s",
            limit,
        )
    except pymysql.Error as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return rows


@router.get("/tasks")
async def business_tasks(limit: int = 20, config=Depends(get_erp_db_config)):
    if config is None:
        raise HTTPException(status_code=503, detail="ERPNext DB not configured")
    try:
        rows = await asyncio.to_thread(
            _erp_query,
            config,
            "SELECT name, subject, status, exp_end_date FROM `tabTask` "
            "WHERE docstatus < 2 ORDER BY creation DESC LIMIT %s",
            limit,
        )
    except pymysql.Error as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return rows


# Metric name → PromQL instant-query. Khớp đúng tên trong
# cluster-bootstrap/business-metrics-exporter/templates/configmap.yaml.
_QUERIES = {
    "customers_active": 'erpnext_customers_total{disabled="0"}',
    "customers_disabled": 'erpnext_customers_total{disabled="1"}',
    "projects_by_status": "erpnext_projects_total",
    "tasks_by_status": "erpnext_tasks_total",
    "tasks_overdue": "erpnext_tasks_overdue_total",
    # FIX (2026-09-21): "Contractor Payment Request" là DocType của app
    # construction_management_app — CHƯA cài trên site thật, bảng không tồn
    # tại, exporter đã đổi sang Material Receipt (Stock Entry) theo supplier.
    # Xem cluster-bootstrap/business-metrics-exporter/templates/configmap.yaml.
    "material_receipts_by_supplier": "erpnext_material_receipts_total",
    "material_receipt_value_by_supplier": "erpnext_material_receipt_value_total",
    "material_issue_value_by_project": "erpnext_material_issue_value_total",
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
