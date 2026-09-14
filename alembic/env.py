from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db.base import Base
from app.db import models  # noqa: F401  — важно для autogenerate

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Подставляем URL из настроек (sync-драйвер)
config.set_main_option(
    "sqlalchemy.url",
    f"postgresql+psycopg2://{settings.postgres_user}:{settings.postgres_password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
)

target_metadata = Base.metadata

# Индексы, которые Alembic не должен трогать (созданы вручную через op.execute)
IGNORED_INDEXES = {
    "ix_books_authors_gin",
    "ix_books_genres_gin",
    "ix_books_title_fts",
    "ix_books_title_trgm",
    "ix_books_authors_text_trgm",
    "ix_books_series_text_trgm",
    "ix_books_annotation_trgm",
    "ix_authors_name_trgm",
    "ix_authors_display_trgm",
}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "index" and name in IGNORED_INDEXES:
        return False  # Alembic не будет их видеть
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()