"""admin notifications + pending appointment status

Revision ID: 0005_admin_notifications
Revises: 0004_clinic_admin
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_admin_notifications"
down_revision: Union[str, None] = "0004_clinic_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    if "admin_notifications" not in existing:
        op.create_table(
            "admin_notifications",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("clinic_id", sa.Integer, sa.ForeignKey("clinics.id"), nullable=False),
            sa.Column("type", sa.String(50), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text, nullable=True),
            sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id"), nullable=True),
            sa.Column("is_read", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        )
        op.create_index("ix_admin_notifications_clinic_id", "admin_notifications", ["clinic_id"])
        op.create_index("ix_admin_notifications_is_read", "admin_notifications", ["is_read"])
        op.create_index("ix_admin_notifications_created_at", "admin_notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_notifications_created_at", table_name="admin_notifications")
    op.drop_index("ix_admin_notifications_is_read", table_name="admin_notifications")
    op.drop_index("ix_admin_notifications_clinic_id", table_name="admin_notifications")
    op.drop_table("admin_notifications")
