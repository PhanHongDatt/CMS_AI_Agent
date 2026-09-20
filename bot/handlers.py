"""Telegram bot command handlers — all state access via API HTTP client."""

import json

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from bot.api_client import (
    chat_llm,
    decide_approval,
    get_autonomy,
    get_business_customers,
    get_business_metrics,
    get_business_projects,
    get_business_tasks,
    get_cluster_events,
    get_cluster_health,
    get_cluster_pods,
    get_incident,
    get_pending_approvals,
    list_incidents,
    list_pipeline_runs,
    submit_alert,
)
from bot.auth import require_auth
from core.logging import get_logger

logger = get_logger(__name__)


def _api_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"API error {e.response.status_code}: {e.response.text[:100]}"
    return f"Could not reach API: {e}"


@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Agentic DevOps Platform</b>\n\n"
        "Commands:\n"
        "/alert &lt;source&gt; &lt;fingerprint&gt; &lt;severity&gt; — submit alert\n"
        "/status — list active incidents\n"
        "/incident &lt;id&gt; — incident details\n"
        "/pipeline — pipeline run status\n"
        "/pending — approvals waiting for decision\n"
        "/approve &lt;request_id&gt; [reason] — approve action\n"
        "/deny &lt;request_id&gt; [reason] — deny action\n"
        "/autonomy — autonomy levels per action type\n"
        "/help — show this message",
        parse_mode="HTML",
    )


@require_auth
async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /alert &lt;source&gt; &lt;fingerprint&gt; &lt;severity&gt; [domain]\n"
            "Example: /alert prometheus pod-crash-001 high infrastructure",
            parse_mode="HTML",
        )
        return

    source, fingerprint, severity = context.args[0], context.args[1], context.args[2]
    domain = context.args[3] if len(context.args) > 3 else "infrastructure"

    try:
        result = await submit_alert(source, fingerprint, severity, domain)
    except Exception as e:
        await update.message.reply_text(f"Failed to submit alert: {_api_error(e)}")
        return

    if result.get("is_duplicate"):
        await update.message.reply_text(
            f"Duplicate — existing incident: <code>{result['incident_id']}</code>\n"
            f"Status: {result['status']}",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"Alert received. Incident created:\n"
            f"ID: <code>{result['incident_id']}</code>\n"
            f"Severity: {result['severity'].upper()}\n"
            f"Pipeline started in background.",
            parse_mode="HTML",
        )


@require_auth
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        incidents = await list_incidents()
    except Exception as e:
        await update.message.reply_text(f"Failed: {_api_error(e)}")
        return

    if not incidents:
        await update.message.reply_text("No active incidents.")
        return

    lines = [f"<b>{len(incidents)} active incident(s):</b>"]
    for inc in incidents:
        lines.append(
            f"\n• <code>{inc['id'][:8]}...</code> [{inc['severity'].upper()}] "
            f"{inc['status']} — {inc['source']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_auth
async def cmd_incident(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /incident <id>")
        return

    try:
        inc = await get_incident(context.args[0])
    except Exception as e:
        await update.message.reply_text(f"Failed: {_api_error(e)}")
        return

    if inc is None:
        await update.message.reply_text(
            f"Incident <code>{context.args[0]}</code> not found.", parse_mode="HTML"
        )
        return

    text = (
        f"<b>Incident</b> <code>{inc['id']}</code>\n"
        f"Source: {inc['source']}\n"
        f"Domain: {inc['domain']}\n"
        f"Severity: {inc['severity'].upper()}\n"
        f"Status: {inc['status']}\n"
        f"Fingerprint: <code>{inc['fingerprint']}</code>\n"
        f"Evidence items: {len(inc['evidence_ids'])}\n"
        f"Created: {inc['created_at']}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


@require_auth
async def cmd_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        runs = await list_pipeline_runs()
    except Exception as e:
        await update.message.reply_text(f"Failed: {_api_error(e)}")
        return

    if not runs:
        await update.message.reply_text("No pipeline runs yet.")
        return

    lines = [f"<b>{len(runs)} pipeline run(s):</b>"]
    for run in runs:
        score = f"{run['confidence_score']:.0%}" if run["confidence_score"] is not None else "N/A"
        lines.append(
            f"\n• <code>{run['incident_id'][:8]}...</code> — <b>{run['stage']}</b>\n"
            f"  Confidence: {score} | Policy: {run['policy_decision'] or 'N/A'}"
            + (f"\n  Error: {run['error']}" if run.get("error") else "")
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_auth
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        pending = await get_pending_approvals()
    except Exception as e:
        await update.message.reply_text(f"Failed: {_api_error(e)}")
        return

    if not pending:
        await update.message.reply_text("No pending approvals.")
        return

    lines = [f"<b>{len(pending)} pending approval(s):</b>"]
    for req in pending:
        lines.append(
            f"\n• <code>{req['request_id'][:8]}...</code>\n"
            f"  Action: {req['action_name']} | Risk: {req['risk']}\n"
            f"  Confidence: {req['confidence_score']:.0%}\n"
            f"  RCA: {req['rca_summary'][:80]}\n"
            f"  Full ID: <code>{req['request_id']}</code>"
        )
    lines.append("\nUse /approve or /deny &lt;request_id&gt; [reason]")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_auth
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /approve <request_id> [reason]")
        return

    request_id = context.args[0]
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
    decided_by = update.effective_user.username or str(update.effective_user.id)

    try:
        await decide_approval(request_id, approved=True, decided_by=decided_by, reason=reason)
    except Exception as e:
        await update.message.reply_text(f"Failed: {_api_error(e)}")
        return

    await update.message.reply_text(
        f"✓ APPROVED <code>{request_id[:8]}...</code>\n"
        f"By: {decided_by}" + (f"\nReason: {reason}" if reason else ""),
        parse_mode="HTML",
    )


@require_auth
async def cmd_deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /deny <request_id> [reason]")
        return

    request_id = context.args[0]
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
    decided_by = update.effective_user.username or str(update.effective_user.id)

    try:
        await decide_approval(request_id, approved=False, decided_by=decided_by, reason=reason)
    except Exception as e:
        await update.message.reply_text(f"Failed: {_api_error(e)}")
        return

    await update.message.reply_text(
        f"✗ DENIED <code>{request_id[:8]}...</code>\n"
        f"By: {decided_by}" + (f"\nReason: {reason}" if reason else ""),
        parse_mode="HTML",
    )


@require_auth
async def cmd_autonomy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        summary = await get_autonomy()
    except Exception as e:
        await update.message.reply_text(f"Failed: {_api_error(e)}")
        return

    if not summary:
        await update.message.reply_text("No autonomy data yet.")
        return

    lines = ["<b>Autonomy levels per action type:</b>"]
    for action, info in summary.items():
        sr = f"{info['success_rate']:.0%}" if info["success_rate"] is not None else "N/A"
        lines.append(
            f"\n• <b>{action}</b>: {info['level']}\n"
            f"  Outcomes: {info['outcomes']} | Success: {sr}\n"
            f"  Rollback tested: {info['rollback_tested']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_auth
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hỏi-đáp ngôn ngữ tự nhiên qua Gemini.

    Bắt mọi message text KHÔNG phải lệnh /slash. Đưa câu hỏi + bối cảnh sự cố
    hiện tại vào Gemini → trả lời bằng tiếng Việt. Phân biệt với các CommandHandler
    (đăng ký trước trong bot/app.py nên lệnh /... vẫn ưu tiên).
    """
    question = (update.message.text or "").strip()
    if not question:
        return

    # Bối cảnh: sự cố + trạng thái cluster THẬT (qua api → K8s API, xem
    # api/routes/cluster.py) để trả lời sát thực tế thay vì chỉ dựa incident.
    try:
        incidents = await list_incidents()
    except Exception:
        incidents = []
    incidents_ctx = (
        json.dumps(incidents[:10], ensure_ascii=False, default=str)
        if incidents
        else "(chưa có sự cố nào)"
    )

    try:
        cluster_health = await get_cluster_health()
    except Exception as e:
        cluster_health = {"error": f"không lấy được: {e}"}

    try:
        cluster_events = await get_cluster_events()
    except Exception as e:
        cluster_events = {"error": f"không lấy được: {e}"}

    try:
        cluster_pods = await get_cluster_pods()
    except Exception as e:
        cluster_pods = {"error": f"không lấy được: {e}"}

    try:
        business_metrics = await get_business_metrics()
    except Exception as e:
        business_metrics = {"error": f"không lấy được: {e}"}

    # Chi tiết (tên) — Prometheus chỉ có số liệu tổng hợp, không lưu text.
    try:
        business_customers = await get_business_customers()
    except Exception as e:
        business_customers = {"error": f"không lấy được: {e}"}

    try:
        business_projects = await get_business_projects()
    except Exception as e:
        business_projects = {"error": f"không lấy được: {e}"}

    try:
        business_tasks = await get_business_tasks()
    except Exception as e:
        business_tasks = {"error": f"không lấy được: {e}"}

    system_prompt = (
        "Bạn là trợ lý DevOps của nền tảng Agentic (giám sát Kubernetes, nhận alert, "
        "phân tích RCA, remediation) kiêm trợ lý nghiệp vụ ERPNext. Trả lời NGẮN GỌN, "
        "rõ ràng, bằng tiếng Việt. Dữ liệu bên dưới lấy TRỰC TIẾP từ Kubernetes API, "
        "Prometheus và MariaDB (không phải giả lập). Nếu người dùng muốn thao tác, "
        "gợi ý lệnh phù hợp (/status, /pending, /approve, /deny, /incident, /pipeline, "
        "/autonomy).\n"
        f"Sự cố hiện tại (JSON): {incidents_ctx}\n"
        f"Trạng thái node cluster (JSON): {json.dumps(cluster_health, ensure_ascii=False, default=str)}\n"  # noqa: E501
        f"Danh sách pod theo namespace (JSON): {json.dumps(cluster_pods, ensure_ascii=False, default=str)[:3000]}\n"  # noqa: E501
        f"Sự kiện gần đây theo namespace (JSON): {json.dumps(cluster_events, ensure_ascii=False, default=str)[:2000]}\n"  # noqa: E501
        f"Số liệu nghiệp vụ tổng hợp — khách hàng/dự án/task quá hạn/thanh toán nhà thầu/"
        f"tồn kho/items/đơn bán-mua hàng (JSON): "
        f"{json.dumps(business_metrics, ensure_ascii=False, default=str)[:2000]}\n"
        f"Danh sách khách hàng gần nhất, tối đa 20 (JSON): "
        f"{json.dumps(business_customers, ensure_ascii=False, default=str)[:1500]}\n"
        f"Danh sách dự án gần nhất, tối đa 20 (JSON): "
        f"{json.dumps(business_projects, ensure_ascii=False, default=str)[:1500]}\n"
        f"Danh sách task gần nhất, tối đa 20 (JSON): "
        f"{json.dumps(business_tasks, ensure_ascii=False, default=str)[:1500]}"
    )

    # Gọi qua api /llm/chat → LLMGateway (openai chính, gemini fallback, retry
    # + circuit breaker sẵn có — core/llm/gateway.py). Trước đây bot tự gọi
    # thẳng GeminiProvider, không có fallback khi Gemini quá tải (503
    # UNAVAILABLE) dù OpenAI vẫn khỏe — sửa sau khi user báo lỗi 503 dồn dập.
    try:
        result = await chat_llm(system_prompt=system_prompt, user_message=question)
        await update.message.reply_text(result.get("content") or "(LLM không trả về nội dung)")
    except Exception as e:  # noqa: BLE001 — trả lỗi về người dùng thay vì crash bot
        logger.error("nl_chat_failed", error=str(e))
        await update.message.reply_text(f"Lỗi khi gọi LLM: {e}")
