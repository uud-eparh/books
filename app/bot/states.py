"""FSM-состояния бота."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ListContext:
    """Контекст постраничного списка (автор / серия)."""

    kind: Literal["author", "series"]
    key: int | str          # author_id (int) или series_name (str)
    title: str              # для заголовка: «Романович Роман» или «Шиноби [Пастырь]»
    total: int = 0
    page: int = 1
    page_size: int = 20