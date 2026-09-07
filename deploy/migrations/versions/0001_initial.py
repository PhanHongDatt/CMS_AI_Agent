"""Initial schema

Revision ID: 0001
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("fingerprint", sa.Text, nullable=False, index=True),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, default="RECEIVED"),
        sa.Column("evidence_ids", postgresql.ARRAY(sa.Text), nullable=False, default=[]),
        sa.Column("rca_id", sa.Text, nullable=True),
        sa.Column("confidence_id", sa.Text, nullable=True),
        sa.Column("policy_decision_id", sa.Text, nullable=True),
        sa.Column("action_ids", postgresql.ARRAY(sa.Text), nullable=False, default=[]),
        sa.Column("trace_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("entity", sa.Text, nullable=False),
        sa.Column("metric_or_query", sa.Text, nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("unit", sa.Text, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_reference", sa.Text, nullable=False),
        sa.Column("freshness_seconds", sa.Float, nullable=False),
        sa.Column("trust_level", sa.Text, nullable=False, default="UNTRUSTED_DATA"),
        sa.Column("ttl_expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "rca",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("root_cause", sa.Text, nullable=True),
        sa.Column("evidence_ids", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("affected_components", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("alternative_hypotheses", postgresql.JSONB, nullable=False, default=[]),
        sa.Column("recommended_action", sa.Text, nullable=True),
        sa.Column("insufficient_evidence", sa.Boolean, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "confidence_scores",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("incident_id", sa.Text, nullable=False, index=True),
        sa.Column("sub_scores", postgresql.JSONB, nullable=False),
        sa.Column("weights", postgresql.JSONB, nullable=False),
        sa.Column("final_score", sa.Float, nullable=False),
        sa.Column("calibration_version", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("incident_id", sa.Text, nullable=False, index=True),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("inputs", postgresql.JSONB, nullable=False),
        sa.Column("rule_matched", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "actions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("incident_id", sa.Text, nullable=False, index=True),
        sa.Column("policy_decision_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("risk", sa.Text, nullable=False),
        sa.Column("rollback_supported", sa.Boolean, nullable=False),
        sa.Column("rollback_tested", sa.Boolean, nullable=False),
        sa.Column("pre_state_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False, default="PENDING"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("action_id", sa.Text, nullable=False, index=True),
        sa.Column("evidence_before_ids", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("evidence_after_ids", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("comparison", postgresql.JSONB, nullable=False),
        sa.Column("result", sa.Text, nullable=False),
        sa.Column("rollback_triggered", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", sa.Text, nullable=True, index=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("trace_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("verifications")
    op.drop_table("actions")
    op.drop_table("policy_decisions")
    op.drop_table("confidence_scores")
    op.drop_table("rca")
    op.drop_table("evidence")
    op.drop_table("incidents")
