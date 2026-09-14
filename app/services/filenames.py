"""Формирование имён файлов.

Транслитерация русских букв в латиницу (простая таблица).
Санитизация недопустимых символов.
Формирование имён для книг и batch-ZIP.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# Таблица транслитерации (простая, без библиотек)
_RU_EN_TABLE: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D",
    "Е": "E", "Ё": "E", "Ж": "Zh", "З": "Z", "И": "I",
    "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N",
    "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T",
    "У": "U", "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch",
    "Ш": "Sh", "Щ": "Shch", "Ъ": "", "Ы": "Y", "Ь": "",
    "Э": "E", "Ю": "Yu", "Я": "Ya",
}

# Недопустимые в имени файла символы (Windows + Linux)
_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Множественные пробелы
_MULTISPACE_RE = re.compile(r"\s+")

# Максимальная длина имени файла
MAX_FILENAME_LEN = 150


def transliterate(text: str) -> str:
    """Транслитерация русского текста в латиницу.

    Не-русские символы (латиница, цифры, знаки) остаются без изменений.
    """
    if not text:
        return ""
    return "".join(_RU_EN_TABLE.get(c, c) for c in text)


def sanitize_filename(name: str) -> str:
    """Убирает недопустимые символы, схлопывает пробелы, ограничивает длину."""
    if not name:
        return ""
    # Убираем недопустимые символы
    name = _ILLEGAL_CHARS_RE.sub("", name)
    # Схлопываем пробелы
    name = _MULTISPACE_RE.sub(" ", name).strip()
    # Точка на конце файла недопустима в Windows
    name = name.rstrip(".")
    # Ограничиваем длину
    if len(name) > MAX_FILENAME_LEN:
        name = name[:MAX_FILENAME_LEN].rstrip()
    return name


def make_book_filename(title: str, authors: list[str], ext: str = "fb2") -> str:
    """Имя файла для книги: '{Author} - {Title}.fb2'.

    Всё транслитерируется и санитизируется.
    """
    # Автор: берём первого (если несколько — через точку с запятой)
    if authors:
        author_raw = "; ".join(a for a in authors if a)
    else:
        author_raw = "Unknown"

    author_lat = sanitize_filename(transliterate(author_raw)) or "Unknown"
    title_lat = sanitize_filename(transliterate(title)) or "Untitled"

    return f"{author_lat} - {title_lat}.{ext}"


def make_unique_filename(
    base_filename: str, existing: set[str]
) -> str:
    """Если имя занято — добавляет '(1)', '(2)' и т.д. перед расширением.

    Args:
        base_filename: желаемое имя (например, 'Author - Title.fb2').
        existing: множество уже используемых имён.

    Returns:
        Уникальное имя.
    """
    if base_filename not in existing:
        return base_filename

    # Разбиваем на основу и расширение
    if "." in base_filename:
        stem, ext = base_filename.rsplit(".", 1)
        ext = "." + ext
    else:
        stem, ext = base_filename, ""

    n = 1
    while True:
        candidate = f"{stem} ({n}){ext}"
        if candidate not in existing:
            return candidate
        n += 1


def make_batch_filename(
    job_id: str,
    *,
    prefix: str = "Flibusta",
    ext: str = "zip",
) -> str:
    """Имя batch-ZIP: 'Flibusta_2026-09-14_a3f7c9.zip'.

    job_id — UUID (36 символов). Берём первые 6 символов для краткости.
    """
    date_part = datetime.now().strftime("%Y-%m-%d")
    short_id = job_id.replace("-", "")[:6]
    return f"{prefix}_{date_part}_{short_id}.{ext}"