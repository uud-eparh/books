"""add authors and book_authors

Revision ID: c7cbe01c23ed
Revises: 89738bce34b6
Create Date: 2026-09-11 13:40:15.892739

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7cbe01c23ed'
down_revision: Union[str, None] = '89738bce34b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('authors',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.Column('books_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', name='uq_authors_name')
    )
    op.create_table('book_authors',
    sa.Column('book_id', sa.BigInteger(), nullable=False),
    sa.Column('author_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['authors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('book_id', 'author_id')
    )
    op.create_index('ix_book_authors_author_id', 'book_authors', ['author_id'], unique=False)

    # Backfill: authors из books.authors
    op.execute("""
        INSERT INTO authors (name, display_name)
        SELECT DISTINCT
            a AS name,
            array_to_string(
                array_remove(string_to_array(a, ','), ''),
                ' '
            ) AS display_name
        FROM books, unnest(authors) AS a
        WHERE a IS NOT NULL AND a != ''
        ON CONFLICT (name) DO NOTHING
    """)

    # Backfill: book_authors
    op.execute("""
        INSERT INTO book_authors (book_id, author_id)
        SELECT b.id, a.id
        FROM books b, unnest(b.authors) AS author_name
        JOIN authors a ON a.name = author_name
        ON CONFLICT DO NOTHING
    """)

    # Обновить счётчики
    op.execute("""
        UPDATE authors a
        SET books_count = (
            SELECT COUNT(*) FROM book_authors WHERE author_id = a.id
        )
    """)

    # Trigram-индексы
    op.execute("CREATE INDEX ix_authors_name_trgm ON authors USING GIN (name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_authors_display_trgm ON authors USING GIN (display_name gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_authors_display_trgm")
    op.execute("DROP INDEX IF EXISTS ix_authors_name_trgm")
    op.drop_index('ix_book_authors_author_id', table_name='book_authors')
    op.drop_table('book_authors')
    op.drop_table('authors')