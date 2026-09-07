"""Telegram bot command handlers — all state access via API HTTP client."""

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from bot.api_client import (
    decide_approval,
    get_autonomy,
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
        await update.message.reply_text(f"Incident <code>{context.args[0]}</code> not found.", parse_mode="HTML")
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
