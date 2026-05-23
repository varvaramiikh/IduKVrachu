"""directions layer between clinic and service; materials link to direction

Revision ID: 0006_directions
Revises: 0005_admin_notifications
Create Date: 2026-05-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_directions"
down_revision: Union[str, None] = "0005_admin_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_col(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    # ── 1. Create directions table ────────────────────────────
    if "directions" not in existing:
        op.create_table(
            "directions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("clinic_id", sa.Integer, sa.ForeignKey("clinics.id"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("icon", sa.String(10), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        )
        op.create_index("ix_directions_clinic_id", "directions", ["clinic_id"])

    directions_t = sa.table(
        "directions",
        sa.column("id", sa.Integer),
        sa.column("clinic_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("icon", sa.String),
        sa.column("color", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    # ── 2. Add services.direction_id (nullable initially) ─────
    if not _has_col(insp, "services", "direction_id"):
        with op.batch_alter_table("services") as batch_op:
            batch_op.add_column(sa.Column(
                "direction_id",
                sa.Integer,
                sa.ForeignKey("directions.id", name="fk_services_direction_id"),
                nullable=True,
            ))

    services_t = sa.table(
        "services",
        sa.column("id", sa.Integer),
        sa.column("clinic_id", sa.Integer),
        sa.column("direction_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("icon", sa.String),
    )

    # ── 3. For each clinic with services, create a default direction and link existing services
    if _has_col(insp, "services", "clinic_id"):
        clinic_ids = list(bind.execute(sa.text("SELECT DISTINCT clinic_id FROM services WHERE clinic_id IS NOT NULL")).scalars())

        def _next_direction_id() -> int:
            return int(bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM directions")).scalar() or 0) + 1

        # Pick the icon of the most-common service in each clinic as a sensible default
        for cid in clinic_ids:
            # Skip if this clinic already has any direction (idempotency).
            existing_dir = bind.execute(
                sa.text("SELECT id FROM directions WHERE clinic_id = :cid LIMIT 1"),
                {"cid": cid},
            ).scalar()
            if existing_dir is not None:
                # Link services without direction_id to this existing direction.
                bind.execute(
                    sa.text(
                        "UPDATE services SET direction_id = :did WHERE clinic_id = :cid AND direction_id IS NULL"
                    ),
                    {"did": existing_dir, "cid": cid},
                )
                continue
            icon_row = bind.execute(
                sa.text("SELECT icon FROM services WHERE clinic_id = :cid AND icon IS NOT NULL AND icon != '' LIMIT 1"),
                {"cid": cid},
            ).first()
            default_icon = icon_row[0] if icon_row else "doctor"
            new_id = _next_direction_id()
            bind.execute(
                directions_t.insert().values(
                    id=new_id,
                    clinic_id=cid,
                    name="Услуги",
                    description="",
                    icon=default_icon,
                    color="#128395",
                    is_active=True,
                )
            )
            bind.execute(
                sa.text("UPDATE services SET direction_id = :did WHERE clinic_id = :cid"),
                {"did": new_id, "cid": cid},
            )

    # ── 4. Drop services.clinic_id; make direction_id NOT NULL
    if _has_col(insp, "services", "clinic_id"):
        # Drop the orphan rows (services with no clinic, if any) so we don't violate NOT NULL.
        bind.execute(sa.text("DELETE FROM services WHERE direction_id IS NULL"))
        with op.batch_alter_table("services") as batch_op:
            batch_op.alter_column("direction_id", existing_type=sa.Integer, nullable=False)
            batch_op.drop_column("clinic_id")
    else:
        with op.batch_alter_table("services") as batch_op:
            batch_op.alter_column("direction_id", existing_type=sa.Integer, nullable=False)

    # ── 5. Add content_modules.direction_id and backfill from service_id ─
    if not _has_col(insp, "content_modules", "direction_id"):
        with op.batch_alter_table("content_modules") as batch_op:
            batch_op.add_column(sa.Column(
                "direction_id",
                sa.Integer,
                sa.ForeignKey("directions.id", name="fk_content_modules_direction_id"),
                nullable=True,
            ))
        op.create_index("ix_content_modules_direction_id", "content_modules", ["direction_id"])

    if _has_col(insp, "content_modules", "service_id"):
        bind.execute(sa.text(
            "UPDATE content_modules SET direction_id = ("
            "    SELECT direction_id FROM services WHERE services.id = content_modules.service_id"
            ") WHERE direction_id IS NULL"
        ))
        with op.batch_alter_table("content_modules") as batch_op:
            batch_op.drop_column("service_id")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Restore content_modules.service_id (best-effort: cannot recover original mapping)
    if not _has_col(insp, "content_modules", "service_id"):
        with op.batch_alter_table("content_modules") as batch_op:
            batch_op.add_column(sa.Column(
                "service_id",
                sa.Integer,
                sa.ForeignKey("services.id", name="fk_content_modules_service_id"),
                nullable=True,
            ))

    # Restore services.clinic_id from direction
    if not _has_col(insp, "services", "clinic_id"):
        with op.batch_alter_table("services") as batch_op:
            batch_op.add_column(sa.Column(
                "clinic_id",
                sa.Integer,
                sa.ForeignKey("clinics.id", name="fk_services_clinic_id"),
                nullable=True,
            ))
        bind.execute(sa.text(
            "UPDATE services SET clinic_id = ("
            "    SELECT clinic_id FROM directions WHERE directions.id = services.direction_id"
            ")"
        ))
        with op.batch_alter_table("services") as batch_op:
            batch_op.alter_column("clinic_id", existing_type=sa.Integer, nullable=False)
            batch_op.drop_column("direction_id")

    if "ix_directions_clinic_id" in {i["name"] for i in insp.get_indexes("directions")}:
        op.drop_index("ix_directions_clinic_id", table_name="directions")
    op.drop_table("directions")
