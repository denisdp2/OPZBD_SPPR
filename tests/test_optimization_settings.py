import random
from itertools import combinations

import pytest

from app.core.models import Item, Problem, Profile, Requirement
from app.optimization import get_optimizer
from app.optimization.pareto_3d import pareto_front_3d


def test_free_slow_measure_does_not_replace_a_faster_paid_alternative():
    problem = Problem(
        requirements=["R1"],
        mandatory=["R1"],
        period_months=1,
        items=[
            Item(id="FREE", kind="org", name="FREE", covers=["R1"]),
            Item(id="FAST", kind="tool", name="FAST", covers=["R1"]),
        ],
        costs={"FREE": 0, "FAST": 10},
        implementation_days={"FREE": 100, "FAST": 1},
    )
    front = pareto_front_3d(problem)
    assert any(row.selected == ["FAST"] and row.total_implementation_days == 1 for row in front)
    assert any(row.selected == ["FREE"] and row.cost == 0 for row in front)


def test_three_objective_components_match_exhaustive_search():
    for seed in range(10):
        rng = random.Random(seed)
        requirements = [f"R{i}" for i in range(4)]
        items = [
            Item(
                id=str(i),
                kind="tool",
                name=str(i),
                covers=rng.sample(requirements[i % 2 :: 2], rng.randint(1, 2)),
            )
            for i in range(6)
        ]
        problem = Problem(
            requirements=requirements,
            mandatory=["R0"],
            period_months=1,
            items=items,
            costs={item.id: rng.randrange(6) for item in items},
            implementation_days={item.id: rng.randrange(6) for item in items},
        )
        points = set()
        for size in range(len(items) + 1):
            for chosen in combinations(items, size):
                covered = {code for item in chosen for code in item.covers}
                points.add(
                    (
                        sum(problem.costs[item.id] for item in chosen),
                        sum(problem.implementation_days[item.id] for item in chosen),
                        len(covered),
                        "R0" in covered,
                    )
                )
        expected = {
            point
            for point in points
            if not any(
                other != point
                and other[0] <= point[0]
                and other[1] <= point[1]
                and other[2] >= point[2]
                and (other[3] or not point[3])
                for other in points
            )
        }
        actual = {
            (row.cost, row.total_implementation_days, row.covered_count, row.feasible)
            for row in pareto_front_3d(problem)
        }
        assert actual == expected, seed


def alternatives():
    return Problem(
        requirements=["R1", "R2", "R3"],
        mandatory=["R1"],
        period_months=1,
        items=[
            Item(id="A", kind="tool", name="A", covers=["R1"]),
            Item(id="B", kind="tool", name="B", covers=["R1", "R2"]),
            Item(id="C", kind="tool", name="C", covers=["R1", "R2", "R3"]),
        ],
        costs={"A": 1, "B": 5, "C": 10},
    )


def test_objective_modes_are_distinct():
    problem = alternatives()
    assert get_optimizer("boolean-ilp").solve(problem, "min_cost").cost == 1
    assert get_optimizer("branch-bound").solve(problem, "max_coverage", 10).covered_count == 3
    compromise = get_optimizer("multiobjective").solve(problem, "compromise")
    assert compromise.cost == 5 and compromise.covered_count == 2
    with pytest.raises(ValueError, match="Компромисс"):
        get_optimizer("multiobjective").solve(problem, "min_cost")


def test_user_can_override_a_profile_without_changing_the_template(client):
    repo = client.app.state.repo
    for code in ("R1", "R2"):
        repo.upsert_requirement(Requirement(id=code, title=code))
    repo.upsert_profile(Profile(id="K1", name="Шаблон", mandatory=["R1"]))
    repo.upsert_item(Item(id="A", kind="tool", name="A", covers=["R2"]))
    scenario = {
        "profile_id": "K1",
        "requirements": ["R1", "R2"],
        "candidates": [{"item_id": "A", "capex": 10, "opex_month": 0}],
    }
    assert not client.post("/api/evaluate", json=scenario).json()["all_mandatory_covered"]
    scenario["mandatory"] = ["R2"]
    assert client.post("/api/evaluate", json=scenario).json()["all_mandatory_covered"]
    scenario["mandatory"] = []
    assert client.post("/api/evaluate", json=scenario).json()["all_mandatory_covered"]
    assert repo.get_profile("K1").mandatory == ["R1"]
    user = client.post("/api/auth/login", json={"login": "user", "password": "user"}).json()
    path = f"/api/users/{user['id']}/draft"
    draft = {"profile_id": "K1", "mandatory": [], "mode": "compromise", "use_budget": True}
    assert client.put(path, json=draft).status_code == 204
    restored = client.get(path).json()
    assert restored["mandatory"] == [] and restored["mode"] == "compromise"
    assert restored["use_budget"]


def test_api_rejects_an_incompatible_algorithm_and_mode(client):
    body = {
        "scenario": {"requirements": [], "candidates": []},
        "algorithm": "multiobjective",
        "mode": "min_cost",
    }
    assert client.post("/api/optimize", json=body).status_code == 422
    body["mode"] = "compromise"
    assert client.post("/api/optimize", json=body).status_code == 200
    body["algorithm"] = "boolean-ilp"
    assert client.post("/api/optimize", json=body).status_code == 422


def exhaustive(problem):
    rows = []
    for size in range(len(problem.items) + 1):
        for chosen in combinations(problem.items, size):
            covered = set().union(*(set(item.covers) for item in chosen)) if chosen else set()
            rows.append(
                (
                    sum(problem.costs[item.id] for item in chosen),
                    len(covered),
                    set(problem.mandatory) <= covered,
                    len(covered & set(problem.mandatory)),
                )
            )
    return rows


@pytest.mark.parametrize("seed", range(30))
def test_exact_methods_match_exhaustive_search(seed):
    rng = random.Random(seed)
    requirements = [f"R{i}" for i in range(5)]
    problem = Problem(
        requirements=requirements,
        mandatory=rng.sample(requirements, rng.randrange(6)),
        period_months=1,
        items=[
            Item(
                id=str(i),
                kind="tool",
                name=str(i),
                covers=[
                    r
                    for r in (
                        requirements
                        if seed % 2 == 0
                        else requirements[:2]
                        if i < 3
                        else requirements[2:]
                    )
                    if rng.randrange(2)
                ],
            )
            for i in range(7)
        ],
        costs={str(i): rng.randrange(8) for i in range(7)},
    )
    rows = exhaustive(problem)
    expected_front = {
        (c, v, ok)
        for c, v, ok, _ in rows
        if not any(
            a <= c and b >= v and (a < c or b > v) and (feasible or not ok)
            for a, b, feasible, _ in rows
        )
    }
    for name in ("boolean-ilp", "branch-bound"):
        optimizer = get_optimizer(name)
        actual_front = {(s.cost, s.covered_count, s.feasible) for s in optimizer.pareto(problem)}
        assert actual_front == expected_front
        for mode, budget in (("min_cost", None), ("max_coverage", 8)):
            affordable = [row for row in rows if budget is None or row[0] <= budget]
            feasible = [row for row in affordable if row[2]]
            key = (
                (
                    (lambda row: (row[0], -row[1]))
                    if mode == "min_cost"
                    else (lambda row: (-row[1], row[0]))
                )
                if feasible
                else (lambda row: (-row[3], -row[1], row[0]))
            )
            expected = min(feasible or affordable, key=key)
            solution = optimizer.solve(problem, mode, budget)
            assert (solution.cost, solution.covered_count, solution.feasible) == expected[:3]


@pytest.mark.parametrize("name", ["boolean-ilp", "branch-bound"])
@pytest.mark.parametrize("count", [30, 60, 100])
def test_large_independent_sets_and_their_frontiers(name, count):
    ids = [str(i) for i in range(count)]
    problem = Problem(
        requirements=ids,
        mandatory=ids,
        period_months=1,
        items=[Item(id=key, name=key, kind="tool", covers=[key]) for key in ids],
        costs={key: 1 for key in ids},
    )
    optimizer = get_optimizer(name)
    result = optimizer.solve(problem, "min_cost")
    assert result.feasible and result.cost == count and result.covered_count == count
    limited = optimizer.solve(problem, "max_coverage", count // 2)
    assert not limited.feasible and limited.covered_count == count // 2
    assert len(optimizer.pareto(problem)) == count + 1


def test_search_limit_returns_an_error_instead_of_an_approximation(client, monkeypatch):
    import app.optimization.search as search

    monkeypatch.setattr(search, "MAX_STATES", 1)
    repo = client.app.state.repo
    repo.upsert_requirement(Requirement(id="R", title="R"))
    repo.upsert_item(Item(id="A", name="A", kind="tool", covers=["R"]))
    body = {
        "scenario": {"requirements": ["R"], "candidates": [{"item_id": "A", "capex": 1}]},
        "algorithm": "boolean-ilp",
    }
    for route in ("/api/optimize", "/api/pareto"):
        response = client.post(route, json=body)
        assert response.status_code == 422 and "предел" in response.json()["detail"]
