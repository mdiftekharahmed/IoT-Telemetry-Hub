"""Add is_permanent and description columns to parameters table.

Revision ID: 0007_parameter_meta
Revises: 0006_coldchain
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_parameter_meta"
down_revision = "0006_coldchain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("parameters") as batch_op:
        batch_op.add_column(
            sa.Column("is_permanent", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("description", sa.String(255), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("parameters") as batch_op:
        batch_op.drop_column("description")
        batch_op.drop_column("is_permanent")

