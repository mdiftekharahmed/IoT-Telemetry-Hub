"""ColdChain: full schema extension.

Adds: users (replaces single-role admins), fridges, batches, batch_movements,
readings, nonces, security_events, audit_log (with trigger), alerts,
ml_predictions, relocation_suggestions.

The existing tables (devices, parameters, telemetry, telemetry_records,
ingested_messages, admin_sessions, user_profiles) are untouched.
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_coldchain"
down_revision = "8c5a1813525a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users (replaces single-role admins for ColdChain; admins table kept) ──
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("bcrypt_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="pharmacist"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("failed_logins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # ── fridges ───────────────────────────────────────────────────────────────
    op.create_table(
        "fridges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("capacity_slots", sa.Integer, nullable=False, server_default="10"),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("device_id", sa.String(64),
                  sa.ForeignKey("devices.device_id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # ── batches ───────────────────────────────────────────────────────────────
    op.create_table(
        "batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("vaccine_name", sa.String(120), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("fridge_id", sa.Integer,
                  sa.ForeignKey("fridges.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("exposure_weighted_min", sa.Float, nullable=False, server_default="0"),
        sa.Column("last_exposure_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="OK"),
        sa.Column("discard_latched", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("qr_token", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # ── batch_movements ───────────────────────────────────────────────────────
    op.create_table(
        "batch_movements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Integer,
                  sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("from_fridge_id", sa.Integer, nullable=True),
        sa.Column("to_fridge_id", sa.Integer, nullable=True),
        sa.Column("moved_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("reason", sa.String(32), nullable=False, server_default="manual"),
    )

    # ── readings (ColdChain telemetry, replaces generic telemetry for nodes) ──
    op.create_table(
        "readings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(64),
                  sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temp_c", sa.Float, nullable=False),
        sa.Column("door_open", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("door_open_s", sa.Integer, nullable=False, server_default="0"),
        sa.Column("compressor_on", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("lockout_s", sa.Integer, nullable=False, server_default="0"),
        sa.Column("power_source", sa.String(16), nullable=False, server_default="MAINS"),
        sa.Column("mains_present", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("battery_pct", sa.Float, nullable=True),
        sa.Column("battery_v", sa.Float, nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="SAFE"),
        sa.Column("red_latched", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sim_mode", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("ts_source", sa.String(16), nullable=False, server_default="ntp"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_readings_device_seq", "readings", ["device_id", "seq"])
    op.create_index("ix_readings_device_ts", "readings", ["device_id", "ts"])

    # ── nonces ────────────────────────────────────────────────────────────────
    op.create_table(
        "nonces",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(64),
                  sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_nonces_device_nonce", "nonces", ["device_id", "nonce"])
    op.create_index("ix_nonces_seen_at", "nonces", ["seen_at"])

    # ── security_events ───────────────────────────────────────────────────────
    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("raw_excerpt", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_security_events_device", "security_events", ["device_id"])
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("idx", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])

    # PostgreSQL trigger to block UPDATE/DELETE on audit_log
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text("""
            CREATE OR REPLACE FUNCTION audit_log_immutable()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'audit_log rows are immutable';
            END;
            $$;
        """))
        connection.execute(sa.text("""
            CREATE TRIGGER trg_audit_log_immutable
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
        """))

    # ── alerts ────────────────────────────────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("batch_id", sa.Integer,
                  sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("sent_via", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("acknowledged_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_device_type", "alerts", ["device_id", "type"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])

    # ── ml_predictions ────────────────────────────────────────────────────────
    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(64),
                  sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_min", sa.Integer, nullable=False),
        sa.Column("predicted_temp", sa.Float, nullable=True),
        sa.Column("breach_prob", sa.Float, nullable=True),
        sa.Column("health_score", sa.Float, nullable=True),
    )
    op.create_index("ix_ml_predictions_device_ts", "ml_predictions", ["device_id", "ts"])

    # ── relocation_suggestions ────────────────────────────────────────────────
    op.create_table(
        "relocation_suggestions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("from_fridge_id", sa.Integer,
                  sa.ForeignKey("fridges.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("confirmed_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── extend devices table ───────────────────────────────────────────────────
    op.add_column("devices", sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("last_seq", sa.Integer, nullable=True))
    op.add_column("devices", sa.Column("fridge_id", sa.Integer,
                  sa.ForeignKey("fridges.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "fridge_id")
    op.drop_column("devices", "last_seq")
    op.drop_column("devices", "last_seen")
    op.drop_table("relocation_suggestions")
    op.drop_table("ml_predictions")
    op.drop_table("alerts")
    op.drop_table("audit_log")
    op.drop_table("security_events")
    op.drop_table("nonces")
    op.drop_index("ix_readings_device_ts", "readings")
    op.drop_table("readings")
    op.drop_table("batch_movements")
    op.drop_table("batches")
    op.drop_table("fridges")
    op.drop_table("users")
