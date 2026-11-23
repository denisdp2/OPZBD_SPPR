from app.core.models import Item, Problem
from app.optimization.pareto_3d import pareto_front_3d


def test_three_objective_front_keeps_cost_time_coverage_tradeoffs():
    problem = Problem(
        requirements=["R1", "R2"],
        mandatory=["R1"],
        items=[
            Item(id="A", kind="org", name="A", covers=["R1"]),
            Item(id="B", kind="org", name="B", covers=["R1"]),
            Item(id="C", kind="org", name="C", covers=["R2"]),
            Item(id="D", kind="tool", name="D", covers=["R1", "R2"]),
        ],
        costs={"A": 10, "B": 20, "C": 5, "D": 20},
        period_months=12,
        implementation_days={"A": 5, "B": 1, "C": 1, "D": 10},
    )

    front = pareto_front_3d(problem)
    points = {
        (
            round(solution.cost, 2),
            round(solution.total_implementation_days, 1),
            solution.covered_count,
            solution.feasible,
        )
        for solution in front
    }

    # A и B дают одинаковое покрытие, но отличаются стоимостью и сроком.
    # A+C и B+C закрывают два требования: первый дешевле, второй быстрее.
    assert (10, 5, 1, True) in points
    assert (20, 1, 1, True) in points
    assert (15, 6, 2, True) in points
    assert (25, 2, 2, True) in points
    # D дороже и дольше A+C при том же покрытии, поэтому исключается.
    assert (20, 10, 2, True) not in points


def test_three_objective_front_is_pairwise_non_dominated():
    problem = Problem(
        requirements=["R1", "R2", "R3"],
        mandatory=["R1"],
        items=[
            Item(id="A", kind="org", name="A", covers=["R1"]),
            Item(id="B", kind="org", name="B", covers=["R2"]),
            Item(id="C", kind="org", name="C", covers=["R3"]),
            Item(id="D", kind="tool", name="D", covers=["R1", "R2", "R3"]),
        ],
        costs={"A": 10, "B": 20, "C": 5, "D": 40},
        period_months=12,
        implementation_days={"A": 3, "B": 2, "C": 4, "D": 20},
    )

    front = pareto_front_3d(problem)
    for index, left in enumerate(front):
        for right in front[index + 1:]:
            left_dominates = (
                left.cost <= right.cost + 1e-9
                and left.total_implementation_days <= right.total_implementation_days + 1e-9
                and left.covered_count >= right.covered_count
                and (
                    left.cost < right.cost - 1e-9
                    or left.total_implementation_days < right.total_implementation_days - 1e-9
                    or left.covered_count > right.covered_count
                    or (left.feasible and not right.feasible)
                )
                and (left.feasible or not right.feasible)
            )
            right_dominates = (
                right.cost <= left.cost + 1e-9
                and right.total_implementation_days <= left.total_implementation_days + 1e-9
                and right.covered_count >= left.covered_count
                and (
                    right.cost < left.cost - 1e-9
                    or right.total_implementation_days < left.total_implementation_days - 1e-9
                    or right.covered_count > left.covered_count
                    or (right.feasible and not left.feasible)
                )
                and (right.feasible or not left.feasible)
            )
            assert not left_dominates
            assert not right_dominates


def test_three_objective_front_obeys_label_limit():
    problem = Problem(
        requirements=["R1"],
        mandatory=["R1"],
        items=[
            Item(id="A", kind="org", name="A", covers=["R1"]),
            Item(id="B", kind="org", name="B", covers=["R1"]),
        ],
        costs={"A": 10, "B": 20},
        period_months=12,
        implementation_days={"A": 5, "B": 1},
    )

    try:
        pareto_front_3d(problem, max_labels=1)
    except ValueError as exc:
        assert "лимит" in str(exc)
    else:
        raise AssertionError("Ожидалась защита от превышения лимита меток")


def test_zero_cost_items_are_included_with_their_duration():
    problem = Problem(
        requirements=["R1", "R2"],
        mandatory=["R1"],
        items=[
            Item(id="FREE", kind="org", name="Бесплатная мера", covers=["R1"]),
            Item(id="PAID", kind="tool", name="Платное средство", covers=["R2"]),
        ],
        costs={"FREE": 0, "PAID": 10},
        period_months=12,
        implementation_days={"FREE": 2.5, "PAID": 1.5},
    )

    front = pareto_front_3d(problem)
    assert any(
        solution.covered_count == 1
        and solution.feasible
        and solution.total_implementation_days == 2.5
        and "FREE" in solution.selected
        for solution in front
    )


def test_empty_infeasible_baseline_is_not_dropped_from_front():
    problem = Problem(
        requirements=["R1"],
        mandatory=["R1"],
        items=[Item(id="A", kind="org", name="A", covers=["R1"])],
        costs={"A": 10},
        period_months=12,
        implementation_days={"A": 2},
    )

    front = pareto_front_3d(problem)
    assert any(
        solution.cost == 0
        and solution.covered_count == 0
        and solution.total_implementation_days == 0
        and not solution.feasible
        for solution in front
    )
