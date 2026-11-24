from app.core.models import Candidate, Item, OptimizeRequest, Problem, Requirement, Scenario
from app.optimization import get_optimizer, list_optimizers

REQS = [f"REQ-0{i}" for i in range(1, 8)]


def demo_problem() -> Problem:
    items = [
        Item(id="iam-suite", kind="tool", name="IAM", covers=["REQ-01", "REQ-02"]),
        Item(id="endpoint-protection", kind="tool", name="EP", covers=["REQ-04", "REQ-06"]),
        Item(id="log-monitoring", kind="tool", name="Log", covers=["REQ-03", "REQ-06"]),
        Item(id="backup-system", kind="tool", name="Backup", covers=["REQ-05"]),
        Item(id="access-regulation", kind="org", name="Access", covers=["REQ-02", "REQ-07"]),
        Item(id="incident-plan", kind="org", name="Incidents", covers=["REQ-06", "REQ-07"]),
        Item(id="security-training", kind="org", name="Training", covers=["REQ-01", "REQ-07"]),
    ]
    costs = {
        "iam-suite": 120_000,
        "endpoint-protection": 80_000,
        "log-monitoring": 70_000,
        "backup-system": 40_000,
        "access-regulation": 15_000,
        "incident-plan": 10_000,
        "security-training": 8_000,
    }
    return Problem(
        requirements=REQS,
        mandatory=["REQ-01", "REQ-02", "REQ-03", "REQ-07"],
        items=items,
        costs=costs,
        period_months=12,
    )


def test_optimizers_are_registered():
    names = {info.name for info in list_optimizers()}
    assert names == {"boolean-ilp", "branch-bound", "greedy-cover", "multiobjective"}


def test_boolean_ilp_min_cost_covers_mandatory_cheapest():
    problem = demo_problem()
    solution = get_optimizer("boolean-ilp").solve(problem, "min_cost")
    assert solution.feasible is True
    assert set(problem.mandatory) <= _covered(problem, solution.selected)
    # IAM закрывает REQ-01 и REQ-02; обучение дешевле IAM, но без REQ-02.
    # Минимум: security-training + access-regulation + log-monitoring = 8k+15k+70k.
    assert set(solution.selected) == {
        "security-training",
        "access-regulation",
        "log-monitoring",
    }
    assert solution.cost == 93_000


def test_boolean_ilp_max_coverage_respects_budget():
    problem = demo_problem()
    solution = get_optimizer("boolean-ilp").solve(problem, "max_coverage", budget=93_000)
    assert solution.feasible is True
    assert solution.cost <= 93_000
    assert solution.covered_count == 5


def test_boolean_ilp_infeasible_when_requirement_has_no_item():
    problem = demo_problem().model_copy(update={"mandatory": ["REQ-01", "MISSING"]})
    solution = get_optimizer("boolean-ilp").solve(problem, "min_cost")
    assert solution.feasible is False


def test_pareto_is_sorted_by_cost_and_non_dominated():
    frontier = get_optimizer("boolean-ilp").pareto(demo_problem())
    assert frontier
    costs = [row.cost for row in frontier]
    assert costs == sorted(costs)
    for i, left in enumerate(frontier):
        for right in frontier[i + 1 :]:
            assert not (
                left.cost <= right.cost
                and left.covered_count >= right.covered_count
                and (left.cost < right.cost or left.covered_count > right.covered_count)
                and (left.feasible or not right.feasible)
            )


def test_free_measure_stays_in_the_set():
    problem = Problem(
        requirements=["REQ-01", "REQ-02"],
        mandatory=["REQ-01", "REQ-02"],
        items=[
            Item(id="tool", kind="tool", name="Tool", covers=["REQ-01", "REQ-02"]),
            Item(id="measure", kind="org", name="Measure", covers=["REQ-01"]),
        ],
        costs={"tool": 1_000, "measure": 0},
        period_months=12,
    )
    for name in ("boolean-ilp", "greedy-cover", "branch-bound", "multiobjective"):
        solution = get_optimizer(name).solve(
            problem, "compromise" if name == "multiobjective" else "min_cost"
        )
        assert solution.feasible is True
        assert solution.cost == 1_000
        assert "measure" in solution.selected
        assert "tool" in solution.selected


def test_greedy_cover_is_feasible_on_demo():
    solution = get_optimizer("greedy-cover").solve(demo_problem(), "min_cost")
    assert solution.feasible is True
    assert solution.cost >= 93_000


def test_branch_bound_matches_boolean_ilp():
    problem = demo_problem()
    exact = get_optimizer("boolean-ilp").solve(problem, "min_cost")
    branched = get_optimizer("branch-bound").solve(problem, "min_cost")
    assert branched.feasible is True
    assert set(branched.selected) == set(exact.selected)
    assert branched.cost == exact.cost
    capped = get_optimizer("branch-bound").solve(problem, "max_coverage", budget=93_000)
    assert capped.feasible is True
    assert capped.cost <= 93_000
    assert capped.covered_count == 5


def test_multiobjective_picks_compromise_on_demo():
    solution = get_optimizer("multiobjective").solve(demo_problem(), "compromise")
    assert solution.feasible is True
    assert solution.cost == 133_000
    assert solution.covered_count == 6
    assert "backup-system" in solution.selected


def test_multiobjective_respects_budget():
    solution = get_optimizer("multiobjective").solve(demo_problem(), "compromise", budget=50_000)
    assert solution.cost <= 50_000


def _assert_pareto(frontier):
    assert frontier
    costs = [row.cost for row in frontier]
    assert costs == sorted(costs)
    for i, left in enumerate(frontier):
        for right in frontier[i + 1 :]:
            assert not (
                left.cost <= right.cost
                and left.covered_count >= right.covered_count
                and (left.cost < right.cost or left.covered_count > right.covered_count)
                and (left.feasible or not right.feasible)
            )


def test_branch_bound_and_multiobjective_pareto_are_non_dominated():
    _assert_pareto(get_optimizer("branch-bound").pareto(demo_problem()))
    _assert_pareto(get_optimizer("multiobjective").pareto(demo_problem()))


def _covered(problem: Problem, selected: list[str]) -> set[str]:
    chosen = set(selected)
    covered: set[str] = set()
    for item in problem.items:
        if item.id in chosen:
            covered.update(item.covers)
    return covered


def test_optimize_api(client):
    app_repo = client.app.state.repo
    for req_id, title in [
        ("REQ-01", "A"),
        ("REQ-02", "B"),
        ("REQ-03", "C"),
        ("REQ-07", "G"),
    ]:
        app_repo.upsert_requirement(Requirement(id=req_id, title=title))
    app_repo.upsert_item(Item(id="iam-suite", kind="tool", name="IAM", covers=["REQ-01", "REQ-02"]))
    app_repo.upsert_item(Item(id="log-monitoring", kind="tool", name="Log", covers=["REQ-03"]))
    app_repo.upsert_item(
        Item(id="access-regulation", kind="org", name="Access", covers=["REQ-02", "REQ-07"])
    )
    app_repo.upsert_item(
        Item(id="security-training", kind="org", name="Train", covers=["REQ-01", "REQ-07"])
    )

    names = {row["name"] for row in client.get("/api/optimizers").json()}
    assert "boolean-ilp" in names

    body = OptimizeRequest(
        algorithm="boolean-ilp",
        mode="min_cost",
        scenario=Scenario(
            mandatory=["REQ-01", "REQ-02", "REQ-03", "REQ-07"],
            requirements=["REQ-01", "REQ-02", "REQ-03", "REQ-07"],
            candidates=[
                Candidate(item_id="iam-suite", capex=120000),
                Candidate(item_id="log-monitoring", capex=70000),
                Candidate(item_id="access-regulation", capex=15000),
                Candidate(item_id="security-training", capex=8000),
            ],
        ),
    )
    response = client.post("/api/optimize", json=body.model_dump())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["feasible"] is True
    assert set(data["selected"]) == {
        "security-training",
        "access-regulation",
        "log-monitoring",
    }

    pareto = client.post("/api/pareto", json=body.model_dump())
    assert pareto.status_code == 200
    assert isinstance(pareto.json(), list)
