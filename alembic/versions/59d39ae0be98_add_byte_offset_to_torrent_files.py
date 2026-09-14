"""add byte_offset to torrent_files

Revision ID: 59d39ae0be98
Revises: c7cbe01c23ed
Create Date: 2026-09-11 14:50:36.769518

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '59d39ae0be98'
down_revision: Union[str, None] = 'c7cbe01c23ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Добавить колонку с server_default=0 (заполнит существующие строки)
    op.add_column(
        'torrent_files',
        sa.Column(
            'byte_offset',
            sa.BigInteger(),
            nullable=False,
            server_default='0',
        ),
    )

    # 2. Backfill: посчитать byte_offset через оконную функцию
    op.execute("""
        UPDATE torrent_files tf
        SET byte_offset = sub.sum_before
        FROM (
            SELECT
                id,
                COALESCE(
                    SUM(size) OVER (
                        PARTITION BY torrent_id
                        ORDER BY file_index
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ),
                    0
                ) AS sum_before
            FROM torrent_files
        ) sub
        WHERE tf.id = sub.id
    """)

    # 3. Убрать server_default (он был нужен только для миграции)
    op.alter_column('torrent_files', 'byte_offset', server_default=None)


def downgrade() -> None:
    op.drop_column('torrent_files', 'byte_offset')