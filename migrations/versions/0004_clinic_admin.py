"""clinic-scoped services + admin users

Revision ID: 0004_clinic_admin
Revises: 0003_doctor_avatar
Create Date: 2026-05-03

"""
import hashlib
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_clinic_admin"
down_revision: Union[str, None] = "0003_doctor_avatar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_col(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    # ── 1. services.clinic_id (nullable initially) ────────────
    if not _has_col(insp, "services", "clinic_id"):
        with op.batch_alter_table("services") as batch_op:
            batch_op.add_column(sa.Column("clinic_id", sa.Integer, sa.ForeignKey("clinics.id"), nullable=True))

    # ── 2. Migrate Clinic.services_json → Service.clinic_id ───
    services_t = sa.table(
        "services",
        sa.column("id", sa.Integer),
        sa.column("clinic_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("icon", sa.String),
        sa.column("service_type", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("mis_external_id", sa.String),
    )
    appts_t = sa.table(
        "appointments",
        sa.column("id", sa.Integer),
        sa.column("clinic_id", sa.Integer),
        sa.column("service_id", sa.Integer),
    )

    has_services_json = _has_col(insp, "clinics", "services_json")
    clinic_rows = list(bind.execute(sa.text("SELECT id, services_json FROM clinics")).fetchall()) if has_services_json else list(bind.execute(sa.text("SELECT id, NULL AS services_json FROM clinics")).fetchall())
    all_services = list(bind.execute(sa.text(
        "SELECT id, name, description, icon, service_type, is_active, mis_external_id, clinic_id FROM services"
    )).fetchall())
    svc_by_id = {row.id: row for row in all_services}

    # mapping[(clinic_id, old_service_id)] = new_service_id
    mapping: dict = {}

    def _next_service_id() -> int:
        result = bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM services")).scalar() or 0
        return int(result) + 1

    for crow in clinic_rows:
        cid = crow.id
        try:
            old_ids = json.loads(crow.services_json or "[]") if crow.services_json else []
        except Exception:
            old_ids = []
        if not isinstance(old_ids, list):
            old_ids = []
        for old_id in old_ids:
            old = svc_by_id.get(old_id)
            if not old:
                continue
            # If the original service is unowned and we haven't taken it yet, reuse it
            if old.clinic_id is None and (cid, old_id) not in mapping:
                bind.execute(
                    services_t.update().where(services_t.c.id == old_id).values(clinic_id=cid)
                )
                # update local cache
                svc_by_id[old_id] = old._replace(clinic_id=cid) if hasattr(old, "_replace") else old
                mapping[(cid, old_id)] = old_id
            else:
                new_id = _next_service_id()
                bind.execute(
                    services_t.insert().values(
                        id=new_id,
                        clinic_id=cid,
                        name=old.name,
                        description=old.description,
                        icon=old.icon,
                        service_type=old.service_type,
                        is_active=old.is_active,
                        mis_external_id=old.mis_external_id,
                    )
                )
                mapping[(cid, old_id)] = new_id

    # ── 3. Remap appointments to per-clinic service rows ──────
    appt_rows = list(bind.execute(sa.text("SELECT id, clinic_id, service_id FROM appointments")).fetchall())
    for arow in appt_rows:
        new_sid = mapping.get((arow.clinic_id, arow.service_id))
        if new_sid is not None and new_sid != arow.service_id:
            bind.execute(
                appts_t.update().where(appts_t.c.id == arow.id).values(service_id=new_sid)
            )
        else:
            # Service not yet linked to this clinic — claim or clone it now
            old = svc_by_id.get(arow.service_id)
            if not old:
                continue
            cur_clinic = bind.execute(
                sa.text("SELECT clinic_id FROM services WHERE id = :sid"),
                {"sid": arow.service_id},
            ).scalar()
            if cur_clinic is None:
                bind.execute(
                    services_t.update().where(services_t.c.id == arow.service_id).values(clinic_id=arow.clinic_id)
                )
                mapping[(arow.clinic_id, arow.service_id)] = arow.service_id
            elif cur_clinic == arow.clinic_id:
                pass  # already correct
            else:
                new_id = _next_service_id()
                bind.execute(
                    services_t.insert().values(
                        id=new_id,
                        clinic_id=arow.clinic_id,
                        name=old.name,
                        description=old.description,
                        icon=old.icon,
                        service_type=old.service_type,
                        is_active=old.is_active,
                        mis_external_id=old.mis_external_id,
                    )
                )
                bind.execute(
                    appts_t.update().where(appts_t.c.id == arow.id).values(service_id=new_id)
                )
                mapping[(arow.clinic_id, arow.service_id)] = new_id

    # ── 4. Assign remaining unowned services to first clinic, or delete if no clinic exists
    first_clinic_id = bind.execute(sa.text("SELECT id FROM clinics ORDER BY id LIMIT 1")).scalar()
    if first_clinic_id is not None:
        bind.execute(sa.text(
            "UPDATE services SET clinic_id = :cid WHERE clinic_id IS NULL"
        ), {"cid": first_clinic_id})
    else:
        bind.execute(sa.text("DELETE FROM services WHERE clinic_id IS NULL"))

    # ── 5. Make services.clinic_id NOT NULL ───────────────────
    with op.batch_alter_table("services") as batch_op:
        batch_op.alter_column("clinic_id", existing_type=sa.Integer, nullable=False)

    # ── 6. Drop clinics.services_json (now unused) ────────────
    if has_services_json:
        with op.batch_alter_table("clinics") as batch_op:
            batch_op.drop_column("services_json")

    # ── 7. Create admin_users table ───────────────────────────
    if "admin_users" not in existing:
        op.create_table(
            "admin_users",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("username", sa.String(100), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("is_superadmin", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("clinic_id", sa.Integer, sa.ForeignKey("clinics.id"), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        )
        op.create_index("ix_admin_users_username", "admin_users", ["username"], unique=True)

    # ── 8. Seed default superadmin from env (idempotent) ──────
    from backend.app.config import settings
    existing_super = bind.execute(
        sa.text("SELECT id FROM admin_users WHERE username = :u"),
        {"u": settings.ADMIN_USERNAME},
    ).scalar()
    if existing_super is None:
        bind.execute(
            sa.text(
                "INSERT INTO admin_users (username, password_hash, full_name, is_superadmin, clinic_id, is_active, created_at) "
                "VALUES (:u, :p, :n, 1, NULL, 1, CURRENT_TIMESTAMP)"
            ),
            {"u": settings.ADMIN_USERNAME, "p": _hash_pw(settings.ADMIN_PASSWORD), "n": "Суперадминистратор"},
        )


def downgrade() -> None:
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_table("admin_users")
    with op.batch_alter_table("clinics") as batch_op:
        batch_op.add_column(sa.Column("services_json", sa.String(500), nullable=True))
    with op.batch_alter_table("services") as batch_op:
        batch_op.alter_column("clinic_id", existing_type=sa.Integer, nullable=True)
        batch_op.drop_column("clinic_id")
