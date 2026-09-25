"""Preserve message boundaries for a column-based telemetry explorer."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telemetry_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("message_id", sa.String(36), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Old readings did not retain message identity. Preserve each as an independent
    # registry entry; never guess that equal device/timestamp means the same message.
    op.execute(sa.text(
        "INSERT INTO telemetry_records (id, device_id, timestamp, received_at) "
        "SELECT id, device_id, timestamp, received_at FROM telemetry"
    ))
    op.add_column("telemetry", sa.Column("record_id", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE telemetry SET record_id = id"))
    with op.batch_alter_table("telemetry") as batch:
        batch.alter_column("record_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_telemetry_record", "telemetry_records", ["record_id"], ["id"])
        batch.create_index("ix_telemetry_record_id", ["record_id"])
    if op.get_context().dialect.name == "postgresql":
        op.execute(sa.text(
            "SELECT setval(pg_get_serial_sequence('telemetry_records', 'id'), "
            "COALESCE((SELECT MAX(id) FROM telemetry_records), 1), "
            "EXISTS(SELECT 1 FROM telemetry_records))"
        ))


def downgrade():
    with op.batch_alter_table("telemetry") as batch:
        batch.drop_index("ix_telemetry_record_id")
        batch.drop_constraint("fk_telemetry_record", type_="foreignkey")
        batch.drop_column("record_id")
    op.drop_table("telemetry_records")
