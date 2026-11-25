"""Общая 0-1 постановка: какое требование закрывает каждый кандидат."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.cover import expand_covers
from app.core.models import Problem

INF = float("inf")


@dataclass(frozen=True)
class CoverInstance:
    item_ids: tuple[str, ...]
    costs: tuple[float, ...]
    masks: tuple[int, ...]
    requirement_ids: tuple[str, ...]
    mandatory_mask: int
    full_mask: int

    @property
    def n(self) -> int:
        return len(self.item_ids)

    @property
    def m(self) -> int:
        return len(self.requirement_ids)


if hasattr(int, "bit_count"):
    popcount = int.bit_count
else:

    def popcount(value: int) -> int:
        return bin(value).count("1")


def encode(problem: Problem) -> CoverInstance:
    requirement_ids = tuple(dict.fromkeys(problem.requirements))
    index = {req_id: bit for bit, req_id in enumerate(requirement_ids)}
    mandatory_mask = 0
    for req_id in dict.fromkeys(problem.mandatory):
        if req_id in index:
            mandatory_mask |= 1 << index[req_id]

    item_ids: list[str] = []
    costs: list[float] = []
    masks: list[int] = []
    seen: set[str] = set()
    catalog = list(problem.items)
    known_reqs = set(requirement_ids)
    for item in catalog:
        if item.id in seen:
            continue
        seen.add(item.id)
        mask = 0
        for req_id in expand_covers(item, catalog, known_reqs):
            bit = index.get(req_id)
            if bit is not None:
                mask |= 1 << bit
        item_ids.append(item.id)
        costs.append(float(problem.costs.get(item.id, 0.0)))
        masks.append(mask)

    full_mask = (1 << len(requirement_ids)) - 1 if requirement_ids else 0
    return CoverInstance(
        item_ids=tuple(item_ids),
        costs=tuple(costs),
        masks=tuple(masks),
        requirement_ids=requirement_ids,
        mandatory_mask=mandatory_mask,
        full_mask=full_mask,
    )
