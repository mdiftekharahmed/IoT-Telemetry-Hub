"""Separate user details from admin credentials in the same database."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_profiles",
        sa.Column(
            "username",
            sa.String(64),
            sa.ForeignKey("admins.username", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("full_name", sa.String(120), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Existing accounts receive an empty profile without altering their credentials.
    op.execute(
        sa.text(
            "INSERT INTO user_profiles (username, created_at, updated_at) "
            "SELECT username, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM admins"
        )
    )


def downgrade():
    op.drop_table("user_profiles")
