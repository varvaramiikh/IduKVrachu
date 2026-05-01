"""admin entities: Doctor, DoctorSchedule, AdminRole + extra columns

Revision ID: 0002_admin_entities
Revises: 0001_initial
Create Date: 2026-04-30

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002_admin_entities"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_col(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    # ── Extend existing tables ────────────────────────────────
    with op.batch_alter_table("services") as batch_op:
        if not _has_col(insp, "services", "description"):
            batch_op.add_column(sa.Column("description", sa.String(500), nullable=True))
        if not _has_col(insp, "services", "icon"):
            batch_op.add_column(sa.Column("icon", sa.String(10), nullable=True))

    with op.batch_alter_table("cities") as batch_op:
        if not _has_col(insp, "cities", "region"):
            batch_op.add_column(sa.Column("region", sa.String(255), nullable=True))

    with op.batch_alter_table("clinics") as batch_op:
        if not _has_col(insp, "clinics", "phone"):
            batch_op.add_column(sa.Column("phone", sa.String(30), nullable=True))
        if not _has_col(insp, "clinics", "worktime"):
            batch_op.add_column(sa.Column("worktime", sa.String(100), nullable=True))
        if not _has_col(insp, "clinics", "services_json"):
            batch_op.add_column(sa.Column("services_json", sa.String(500), nullable=True))

    with op.batch_alter_table("content_modules") as batch_op:
        if not _has_col(insp, "content_modules", "service_id"):
            batch_op.add_column(sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=True))
        if not _has_col(insp, "content_modules", "content_type"):
            batch_op.add_column(sa.Column("content_type", sa.String(100), nullable=True))
        if not _has_col(insp, "content_modules", "duration_minutes"):
            batch_op.add_column(sa.Column("duration_minutes", sa.Integer, nullable=True))
        if not _has_col(insp, "content_modules", "url"):
            batch_op.add_column(sa.Column("url", sa.String(512), nullable=True))
        if not _has_col(insp, "content_modules", "is_active"):
            batch_op.add_column(sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"))

    # ── New tables (skip if already created by 0001's create_all) ────
    if "doctors" not in existing:
        op.create_table(
            "doctors",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("spec", sa.String(255), nullable=True),
            sa.Column("clinic_id", sa.Integer, sa.ForeignKey("clinics.id"), nullable=True),
            sa.Column("exp_years", sa.Integer, nullable=False, server_default="0"),
            sa.Column("min_age", sa.Integer, nullable=False, server_default="0"),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("initials", sa.String(10), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        )

    if "doctor_schedules" not in existing:
        op.create_table(
            "doctor_schedules",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("doctor_id", sa.Integer, sa.ForeignKey("doctors.id"), nullable=False),
            sa.Column("day_of_week", sa.Integer, nullable=False),
            sa.Column("time_slot", sa.String(5), nullable=False),
        )

    if "admin_roles" not in existing:
        op.create_table(
            "admin_roles",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("perms", sa.Text, nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    op.drop_table("admin_roles")
    op.drop_table("doctor_schedules")
    op.drop_table("doctors")

    with op.batch_alter_table("content_modules") as batch_op:
        batch_op.drop_column("is_active")
        batch_op.drop_column("url")
        batch_op.drop_column("duration_minutes")
        batch_op.drop_column("content_type")
        batch_op.drop_column("service_id")

    with op.batch_alter_table("clinics") as batch_op:
        batch_op.drop_column("services_json")
        batch_op.drop_column("worktime")
        batch_op.drop_column("phone")

    with op.batch_alter_table("cities") as batch_op:
        batch_op.drop_column("region")

    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_column("icon")
        batch_op.drop_column("description")
