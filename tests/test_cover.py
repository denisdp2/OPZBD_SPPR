from app.core.cover import expand_covers
from app.core.models import Item, Problem, Requirement
from app.optimization.encoding import encode
from app.storage.sqlite import SQLiteRepository


def test_tool_covers_measure_expands_to_requirements():
    measure = Item(id="access-control", kind="org", name="Контроль учёта", covers=["REQ-01"])
    tool = Item(id="iam", kind="tool", name="IAM", covers=["access-control"])
    assert expand_covers(measure, [measure, tool], ["REQ-01"]) == ["REQ-01"]
    assert expand_covers(tool, [measure, tool], ["REQ-01"]) == ["REQ-01"]


def test_tool_may_still_cover_requirements_directly():
    tool = Item(id="iam", kind="tool", name="IAM", covers=["REQ-01", "REQ-02"])
    assert expand_covers(tool, [tool], ["REQ-01", "REQ-02"]) == ["REQ-01", "REQ-02"]


def test_encode_uses_expanded_covers_for_tools():
    measure = Item(id="access-control", kind="org", name="Контроль учёта", covers=["REQ-01"])
    tool = Item(id="iam", kind="tool", name="IAM", covers=["access-control"])
    instance = encode(
        Problem(
            requirements=["REQ-01"],
            mandatory=["REQ-01"],
            items=[measure, tool],
            costs={"access-control": 1, "iam": 10},
            period_months=12,
        )
    )
    index = {item_id: i for i, item_id in enumerate(instance.item_ids)}
    assert instance.masks[index["iam"]] == 1
    assert instance.masks[index["access-control"]] == 1


def test_uncovered_requirements_follow_measure_links(tmp_path):
    repo = SQLiteRepository(tmp_path / "catalog.sqlite3")
    repo.upsert_requirement(Requirement(id="R1", title="Первое"))
    repo.upsert_requirement(Requirement(id="R2", title="Второе"))
    repo.upsert_item(Item(id="measure", kind="org", name="Мера", covers=["R1"]))
    repo.upsert_item(Item(id="tool", kind="tool", name="ПО", covers=["measure"]))
    assert [req.id for req in repo.uncovered_requirements()] == ["R2"]
