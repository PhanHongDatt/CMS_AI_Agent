"""GET /cluster — trạng thái cluster thật (chỉ đọc), dùng cho bot NL Q&A.

Bot (Telegram) không có K8s client/RBAC riêng — nó gọi HTTP tới api để lấy
ngữ cảnh thật cho câu trả lời, thay vì chỉ dựa vào danh sách incident.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_k8s_namespaces, get_k8s_tools
from mcp.base import MCPError

router = APIRouter(prefix="/cluster", tags=["cluster"])


@router.get("/health")
async def cluster_health(tools=Depends(get_k8s_tools)):
    if tools is None:
        raise HTTPException(status_code=503, detail="K8s evidence gathering not available")
    try:
        result = await tools.k8s_get_cluster_health()
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result.data


@router.get("/events")
async def cluster_events(
    namespace: str | None = None,
    tools=Depends(get_k8s_tools),
    namespaces: list[str] = Depends(get_k8s_namespaces),
):
    if tools is None:
        raise HTTPException(status_code=503, detail="K8s evidence gathering not available")
    target_namespaces = [namespace] if namespace else namespaces
    out: dict[str, list] = {}
    for ns in target_namespaces:
        try:
            result = await tools.k8s_get_events(namespace=ns)
            out[ns] = result.data["events"]
        except MCPError as e:
            out[ns] = [{"error": str(e)}]
    return out


@router.get("/pods")
async def cluster_pods(
    namespace: str | None = None,
    tools=Depends(get_k8s_tools),
    namespaces: list[str] = Depends(get_k8s_namespaces),
):
    if tools is None:
        raise HTTPException(status_code=503, detail="K8s evidence gathering not available")
    target_namespaces = [namespace] if namespace else namespaces
    out: dict[str, list] = {}
    for ns in target_namespaces:
        try:
            result = await tools.k8s_list_pods(namespace=ns)
            out[ns] = result.data["pods"]
        except MCPError as e:
            out[ns] = [{"error": str(e)}]
    return out
