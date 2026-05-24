"""materials decoupled from per-clinic direction: store canonical direction_name

Revision ID: 0007_materials_canonical_direction
Revises: 0006_directions
Create Date: 2026-05-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_materials_canonical_direction"
down_revision: Union[str, None] = "0006_directions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_col(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def _index_names(inspector, table: str) -> set:
    return {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Add direction_name column (nullable while we backfill).
    if not _has_col(insp, "content_modules", "direction_name"):
        with op.batch_alter_table("content_modules") as batch_op:
            batch_op.add_column(sa.Column("direction_name", sa.String(255), nullable=True))

    # 2. Backfill from joined directions.name.
    if _has_col(insp, "content_modules", "direction_id"):
        bind.execute(sa.text(
            "UPDATE content_modules SET direction_name = ("
            "    SELECT name FROM directions WHERE directions.id = content_modules.direction_id"
            ") WHERE direction_name IS NULL AND direction_id IS NOT NULL"
        ))

    # Any rows still without a name (orphaned) get a fallback to keep NOT NULL happy.
    bind.execute(sa.text(
        "UPDATE content_modules SET direction_name = 'Без направления' "
        "WHERE direction_name IS NULL OR direction_name = ''"
    ))

    # 3. Deduplicate: for materials sharing (direction_name, title, content_type),
    #    keep the one with the smallest id and re-point children of the others.
    bind.execute(sa.text("""
        UPDATE content_items
        SET module_id = (
            SELECT MIN(cm2.id) FROM content_modules cm1
            JOIN content_modules cm2
              ON cm2.direction_name = cm1.direction_name
             AND COALESCE(cm2.title, '') = COALESCE(cm1.title, '')
             AND COALESCE(cm2.content_type, '') = COALESCE(cm1.content_type, '')
            WHERE cm1.id = content_items.module_id
        )
        WHERE EXISTS (SELECT 1 FROM content_modules WHERE id = content_items.module_id)
    """))

    bind.execute(sa.text("""
        UPDATE purchases
        SET module_id = (
            SELECT MIN(cm2.id) FROM content_modules cm1
            JOIN content_modules cm2
              ON cm2.direction_name = cm1.direction_name
             AND COALESCE(cm2.title, '') = COALESCE(cm1.title, '')
             AND COALESCE(cm2.content_type, '') = COALESCE(cm1.content_type, '')
            WHERE cm1.id = purchases.module_id
        )
        WHERE EXISTS (SELECT 1 FROM content_modules WHERE id = purchases.module_id)
    """))

    # 4. Drop the duplicate rows (everything except the survivor MIN(id) per group).
    bind.execute(sa.text("""
        DELETE FROM content_modules
        WHERE id NOT IN (
            SELECT MIN(id) FROM content_modules
            GROUP BY direction_name, COALESCE(title, ''), COALESCE(content_type, '')
        )
    """))

    # 5. Drop the now-redundant FK and column, then enforce NOT NULL + index on name.
    if _has_col(insp, "content_modules", "direction_id"):
        existing_idx = _index_names(insp, "content_modules")
        with op.batch_alter_table("content_modules") as batch_op:
            if "ix_content_modules_direction_id" in existing_idx:
                batch_op.drop_index("ix_content_modules_direction_id")
            batch_op.drop_column("direction_id")

    with op.batch_alter_table("content_modules") as batch_op:
        batch_op.alter_column("direction_name", existing_type=sa.String(255), nullable=False)

    # Re-inspect after batch ops to get accurate index list.
    insp = sa.inspect(bind)
    if "ix_content_modules_direction_name" not in _index_names(insp, "content_modules"):
        op.create_index("ix_content_modules_direction_name", "content_modules", ["direction_name"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_col(insp, "content_modules", "direction_id"):
        with op.batch_alter_table("content_modules") as batch_op:
            batch_op.add_column(sa.Column(
                "direction_id",
                sa.Integer,
                sa.ForeignKey("directions.id", name="fk_content_modules_direction_id"),
                nullable=True,
            ))

    # Best-effort: pick any direction with the same name (first by id).
    bind.execute(sa.text("""
        UPDATE content_modules
        SET direction_id = (
            SELECT MIN(id) FROM directions WHERE directions.name = content_modules.direction_name
        )
        WHERE direction_id IS NULL
    """))

    insp = sa.inspect(bind)
    if "ix_content_modules_direction_name" in _index_names(insp, "content_modules"):
        op.drop_index("ix_content_modules_direction_name", table_name="content_modules")

    with op.batch_alter_table("content_modules") as batch_op:
        batch_op.drop_column("direction_name")

    op.create_index("ix_content_modules_direction_id", "content_modules", ["direction_id"])
