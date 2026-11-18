"""Сопоставление: мера закрывает требования, средство подходит под меры."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.core.models import Item


def expand_covers(
    item: Item,
    items: Sequence[Item],
    requirement_ids: Iterable[str] | None = None,
) -> list[str]:
    """Вернуть id требований, которые закрывает элемент.

    Оргмера (``kind="org"``) указывает в ``covers`` коды требований.
    Средство (``kind="tool"``) может указывать коды мер (id оргмер) и/или
    коды требований напрямую. Ссылки на меры разворачиваются в требования.
    """
    known_reqs = set(requirement_ids) if requirement_ids is not None else None
    by_id = {entry.id: entry for entry in items}
    found: list[str] = []
    seen_req: set[str] = set()
    visiting: set[str] = set()

    def is_requirement(ref: str) -> bool:
        if known_reqs is not None:
            return ref in known_reqs
        return ref not in by_id

    def walk(current: Item) -> None:
        if current.id in visiting:
            return
        visiting.add(current.id)
        for ref in current.covers:
            if is_requirement(ref):
                if ref not in seen_req:
                    seen_req.add(ref)
                    found.append(ref)
                continue
            nested = by_id.get(ref)
            if nested is not None:
                walk(nested)
        visiting.remove(current.id)

    walk(item)
    return found
