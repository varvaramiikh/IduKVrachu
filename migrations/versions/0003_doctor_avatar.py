"""doctor avatar column

Revision ID: 0003_doctor_avatar
Revises: 0002_admin_entities
Create Date: 2026-05-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003_doctor_avatar"
down_revision: Union[str, None] = "0002_admin_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_col(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    with op.batch_alter_table("doctors") as batch_op:
        if not _has_col(insp, "doctors", "avatar"):
            batch_op.add_column(sa.Column("avatar", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("doctors") as batch_op:
        batch_op.drop_column("avatar")
