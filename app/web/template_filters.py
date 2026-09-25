"""Jinja2-фильтры для форматирования.

Утилита нормализации ФИО авторов:
  из "Кощиенко,Андрей,Геннадьевич" в "Кощиенко Андрей Геннадьевич"
"""

from __future__ import annotations

import re
from urllib.parse import quote


def normalize_author(raw: str) -> str:
    """Преобразует "Фамилия,Имя,Отчество" → "Фамилия Имя Отчество".

    Пустые части отбрасываются. Хвостовые запятые удаляются.
    """
    if not raw:
        return ""
    # Split by comma, strip, drop empties
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return " ".join(parts)


def normalize_authors(raw_list: list[str] | None) -> str:
    """Список авторов через " ; "."""
    if not raw_list:
        return ""
    return "; ".join(normalize_author(a) for a in raw_list if a)


def format_size(num_bytes: int | None) -> str:
    """Человекочитаемый размер: 1234567 → "1.18 MiB"."""
    if not num_bytes:
        return "—"
    n = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def truncate_text(text: str | None, max_len: int = 200) -> str:
    """Обрезает текст до max_len, добавляя "…"."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


_TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(text: str | None) -> str:
    """Убирает HTML/XML-теги из аннотации."""
    if not text:
        return ""
    return _TAG_RE.sub("", text)


def author_url(author_raw: str) -> str:
    """URL для поиска по автору.

    Принимает "Фамилия,Имя,Отчество" → возвращает "/search?field=author&q=Фамилия Имя Отчество".
    """
    if not author_raw:
        return "/search"
    normalized = normalize_author(author_raw)
    return f"/search?field=author&q={quote(normalized)}"


def series_url(series_name: str) -> str:
    """URL для поиска по серии."""
    if not series_name:
        return "/search"
    return f"/search?field=series&q={quote(series_name)}"


def split_authors(raw_list: list[str] | None) -> list[dict]:
    """Список авторов с нормализованным именем и URL.

    Возвращает список словарей {raw, display, url}.
    """
    if not raw_list:
        return []
    result = []
    for raw in raw_list:
        if not raw:
            continue
        display = normalize_author(raw)
        result.append({
            "raw": raw,
            "display": display,
            "url": author_url(raw),
        })
    return result


def register_filters(env) -> None:
    """Регистрирует все фильтры в Jinja2-окружении."""
    env.filters["normalize_authors"] = normalize_authors
    env.filters["normalize_author"] = normalize_author
    env.filters["format_size"] = format_size
    env.filters["truncate_text"] = truncate_text
    env.filters["strip_tags"] = strip_tags
    # новые:
    env.filters["author_url"] = author_url
    env.filters["series_url"] = series_url
    env.filters["split_authors"] = split_authors
