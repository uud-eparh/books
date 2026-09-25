"""SQLAlchemy-модели.

Схема рассчитана на мульти-торрентность:
  - torrents         — реестр торрентов (инфо-хеш, magnet, путь, версия)
  - torrent_files    — файлы внутри торрентов (архивы и их метаданные)
  - books            — книги из .inpx (привязаны к торренту)
  - library_meta     — метаданные каталога .inpx (name/version/…)
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Torrent(Base):
    """Зарегистрированный торрент."""

    __tablename__ = "torrents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # SHA1 info-hash, 40 hex-символов (нижний регистр)
    info_hash: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)

    name: Mapped[str | None] = mapped_column(String(500))
    magnet: Mapped[str | None] = mapped_column(Text)

    # Куда торрент-клиент сохраняет данные (корень раздачи)
    save_path: Mapped[str] = mapped_column(Text, nullable=False)

    # Тип источника: пока только 'inpx_fb2', в будущем 'epub', 'manual' и т.п.
    source_type: Mapped[str] = mapped_column(String(32), default="inpx_fb2", nullable=False)

    # Версия каталога .inpx (например '20260701'). Позволит делать инкремент-обновления.
    version: Mapped[str | None] = mapped_column(String(64))

    # Размер всех данных торрента (байты) и число файлов
    data_size: Mapped[int | None] = mapped_column(BigInteger)
    files_count: Mapped[int | None] = mapped_column(Integer)

    # Статус: 'active', 'paused', 'removed', 'indexing'
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resume_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    resume_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files: Mapped[list[TorrentFile]] = relationship(
        back_populates="torrent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    books: Mapped[list[Book]] = relationship(
        back_populates="torrent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Torrent id={self.id} hash={self.info_hash[:8]}… name={self.name!r}>"


class TorrentFile(Base):
    """Файл внутри торрента (обычно — один .zip-архив с книгами)."""

    __tablename__ = "torrent_files"
    __table_args__ = (
        UniqueConstraint("torrent_id", "file_index", name="uq_torrent_files_idx"),
        Index("ix_torrent_files_torrent_path", "torrent_id", "path"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    torrent_id: Mapped[int] = mapped_column(
        ForeignKey("torrents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    file_index: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)   # "f.fb2-811194-815075.zip"
    # Смещение начала файла от начала торрента (сумма размеров всех
    # предыдущих файлов). Нужно для точечного скачивания piece-ов.
    byte_offset: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Диапазон piece-ов (нужен для скачивания только нужного файла через libtorrent)
    piece_start: Mapped[int] = mapped_column(Integer, nullable=False)
    piece_end: Mapped[int] = mapped_column(Integer, nullable=False)

    torrent: Mapped[Torrent] = relationship(back_populates="files")

    def __repr__(self) -> str:
        return f"<TorrentFile id={self.id} path={self.path!r} size={self.size}>"


class Book(Base):
    """Книга из .inpx-каталога."""

    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint(
            "torrent_id", "lib_id", "archive_name",
            name="uq_books_torrent_lib_archive",
        ),
        Index("ix_books_lib_id", "lib_id"),
        Index("ix_books_archive", "torrent_id", "archive_name"),
        Index("ix_books_language", "language"),
        Index("ix_books_deleted", "is_deleted"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    torrent_id: Mapped[int] = mapped_column(
        ForeignKey("torrents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # LibID из .inpx (уникален в рамках торрента)
    lib_id: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)

    # Храним авторов как в исходнике: ["Джейн,О. О."]
    authors: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    # Дублирующие текстовые поля для быстрого ILIKE-поиска (заполняются при загрузке)
    authors_text: Mapped[str | None] = mapped_column(Text)
    series_text: Mapped[str | None] = mapped_column(Text)

    series: Mapped[str | None] = mapped_column(Text)
    series_num: Mapped[int | None] = mapped_column(Integer)

    file_size: Mapped[int | None] = mapped_column(BigInteger)

    language: Mapped[str | None] = mapped_column(String(16))
    date_added: Mapped[date | None] = mapped_column(Date)
    annotation: Mapped[str | None] = mapped_column(Text)

    # Имя ZIP-архива внутри торрента: "f.fb2-811194-815075.zip"
    archive_name: Mapped[str] = mapped_column(Text, nullable=False)

    # Файл внутри архива — всегда "{lib_id}.fb2", но сохраняем явно на случай изменений
    file_name: Mapped[str] = mapped_column(Text, nullable=False)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    torrent: Mapped[Torrent] = relationship(back_populates="books")

    authors_rel: Mapped[list[Author]] = relationship(
        secondary="book_authors",
        back_populates="books",
    )

    def __repr__(self) -> str:
        return f"<Book lib_id={self.lib_id} title={self.title[:40]!r}>"


class LibraryMeta(Base):
    """Метаданные каталога .inpx."""

    __tablename__ = "library_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    torrent_id: Mapped[int | None] = mapped_column(
        ForeignKey("torrents.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(String(64))
    chunk_size: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)

    books_count: Mapped[int | None] = mapped_column(Integer)
    archives_count: Mapped[int | None] = mapped_column(Integer)

    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ArchiveEntry(Base):
    """Файл внутри ZIP-архива.

    Индексируется один раз при первичной загрузке библиотеки.
    Позволяет точечно скачивать только нужные piece-ы торрента.
    """

    __tablename__ = "archive_entries"
    __table_args__ = (
        UniqueConstraint("torrent_file_id", "filename", name="uq_archive_entries_file"),
        Index("ix_archive_entries_lib_id", "lib_id"),
        Index("ix_archive_entries_tf_id", "torrent_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    torrent_file_id: Mapped[int] = mapped_column(
        ForeignKey("torrent_files.id", ondelete="CASCADE"), nullable=False
    )

    # Имя файла внутри ZIP: "811194.fb2"
    filename: Mapped[str] = mapped_column(Text, nullable=False)

    # LibID, вычисленный из имени (int(filename.split('.')[0])).
    # NULL, если имя не по шаблону {int}.fb2
    lib_id: Mapped[int | None] = mapped_column(Integer)

    # Размеры
    compressed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uncompressed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Offset локального заголовка от начала ZIP
    local_header_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Метод сжатия: 0=STORED, 8=DEFLATED и т.д.
    compression: Mapped[int] = mapped_column(Integer, nullable=False)

    # CRC32 содержимого
    crc32: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __repr__(self) -> str:
        return f"<ArchiveEntry tf_id={self.torrent_file_id} filename={self.filename!r}>"


class Author(Base):
    """Автор книги."""

    __tablename__ = "authors"
    __table_args__ = (
        UniqueConstraint("name", name="uq_authors_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # "Романович,Роман" — как в .inpx (может быть "Фамилия,Имя,Отчество")
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # "Романович Роман" — для отображения
    display_name: Mapped[str] = mapped_column(Text, nullable=False)

    # Количество книг у автора (денормализовано для быстрого отображения)
    books_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    books: Mapped[list[Book]] = relationship(
        secondary="book_authors",
        back_populates="authors_rel",
    )

    def __repr__(self) -> str:
        return f"<Author id={self.id} name={self.name!r}>"


class BookAuthor(Base):
    """Связь книга ↔ автор (many-to-many)."""

    __tablename__ = "book_authors"
    __table_args__ = (
        Index("ix_book_authors_author_id", "author_id"),
    )

    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )

class BatchJob(Base):
    """Пакетное скачивание книг в ZIP-архив.

    Жизненный цикл:
        pending → downloading → packing → ready
                                       ↓
                                     error / cancelled
    """

    __tablename__ = "batch_jobs"
    __table_args__ = (
        Index("ix_batch_jobs_created_at", "created_at"),
        Index("ix_batch_jobs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID

    # Список lib_id, которые нужно скачать
    lib_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False
    )

    # Текущий статус
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )

    # Прогресс
    total_books: Mapped[int] = mapped_column(Integer, nullable=False)
    done_books: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Текущая книга (для UI)
    current_lib_id: Mapped[int | None] = mapped_column(Integer)

    # Результаты по каждой книге
    completed_lib_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, nullable=False
    )
    failed_lib_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, nullable=False
    )

    # Результат (ZIP-файл)
    file_path: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    # Ошибка (если упал)
    error: Mapped[str | None] = mapped_column(Text)

    # Отмена
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def to_dict(self) -> dict:
        """Сериализация для API/SSE."""
        return {
            "job_id": self.id,
            "status": self.status,
            "total_books": self.total_books,
            "done_books": self.done_books,
            "error_count": self.error_count,
            "progress_percent": round(
                self.done_books / max(1, self.total_books) * 100, 1
            ),
            "current_lib_id": self.current_lib_id,
            "completed_lib_ids": list(self.completed_lib_ids or []),
            "failed_lib_ids": list(self.failed_lib_ids or []),
            "file_size": self.file_size,
            "error": self.error,
            "cancelled": self.cancelled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<BatchJob id={self.id} status={self.status!r} "
            f"{self.done_books}/{self.total_books}>"
        )
