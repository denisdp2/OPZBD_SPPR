"""Замеры точных методов: python -m scripts.benchmark_optimization --sizes 30 60 100."""

import argparse
import json
import random
from time import perf_counter

from app.core.models import Item, Problem
from app.optimization import get_optimizer
from app.optimization.pareto_3d import pareto_front_3d


def problem_for(kind: str, count: int) -> Problem:
    size = count if kind == "independent" else 8
    requirements = [str(i) for i in range(size)]
    rng = random.Random(24)
    items = []
    for i in range(count):
        covers = (
            [str(i)]
            if kind == "independent"
            else requirements
            if kind == "same"
            else rng.sample(requirements, min(3, size))
        )
        items.append(Item(id=f"T{i}", name=f"T{i}", kind="tool", covers=covers))
    return Problem(
        requirements=requirements,
        mandatory=requirements[: max(1, size // 2)],
        items=items,
        costs={item.id: 1 for item in items},
        period_months=1,
        implementation_days={item.id: 1 for item in items},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[30, 60, 100])
    args = parser.parse_args()
    for count in args.sizes:
        if count < 1:
            parser.error("Число кандидатов должно быть положительным")
        for kind in ("same", "independent", "overlap"):
            problem = problem_for(kind, count)
            tasks = []
            for name in ("boolean-ilp", "branch-bound"):
                optimizer = get_optimizer(name)
                tasks.extend(
                    [
                        (name, "min_cost", lambda o=optimizer, p=problem: o.solve(p, "min_cost")),
                        (
                            name,
                            "max_coverage",
                            lambda o=optimizer, p=problem, n=count: o.solve(
                                p, "max_coverage", max(1, n // 2)
                            ),
                        ),
                        (name, "pareto", lambda o=optimizer, p=problem: o.pareto(p)),
                    ]
                )
            tasks.append(("pareto-3d", "pareto", lambda p=problem: pareto_front_3d(p)))
            for name, mode, call in tasks:
                started = perf_counter()
                row = {"case": kind, "candidates": count, "algorithm": name, "mode": mode}
                try:
                    result = call()
                    row.update(status="ok", points=len(result) if isinstance(result, list) else 1)
                except ValueError as exc:
                    row.update(status="limit", error=str(exc))
                row["ms"] = round((perf_counter() - started) * 1000, 3)
                print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
