"""Initial devices, whitelist, telemetry, receipts and admin sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "parameters",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "ingested_messages",
        sa.Column("device_id", sa.String(64), sa.ForeignKey("devices.device_id"), primary_key=True),
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("parameter", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
    )
    op.create_index("ix_telemetry_timestamp_id", "telemetry", ["timestamp", "id"])
    op.create_table(
        "admins",
        sa.Column("username", sa.String(64), primary_key=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(64), sa.ForeignKey("admins.username"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])


def downgrade():
    op.drop_table("admin_sessions")
    op.drop_table("admins")
    op.drop_table("telemetry")
    op.drop_table("ingested_messages")
    op.drop_table("parameters")
    op.drop_table("devices")
