from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.core.models import Item, Requirement
from app.importers.coverage_review import DECISION, ITEM_CODE, REQUIREMENT_CODE
from app.importers.registry import RegistryRecord


def upload(client, rows, **params):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    output = BytesIO()
    workbook.save(output)
    return client.post(
        "/api/admin/coverage/import",
        params=params,
        files={"file": ("review.xlsx", output.getvalue())},
    )


def seed(client):
    repo = client.app.state.repo
    repo.upsert_requirement(Requirement(id="АВЗ.1", title="Антивирусная защита"))
    repo.upsert_requirement(Requirement(id="ИАФ.3", title="Аутентификация"))
    repo.upsert_item(Item(id="ru-software-17", kind="tool", name="=Demo", covers=["ИАФ.3"]))
    repo.upsert_item(Item(id="vr", kind="tool", name="VR и ИИ-протокол встречи"))
    repo.upsert_item(Item(id="org", kind="org", name="Мера"))
    client.app.state.registry.store.upsert(
        [RegistryRecord(reg_number=17, name="Demo", software_class="03.06")]
    )
    return repo


def test_export_is_for_admin_and_leaves_suggestions_unconfirmed(client):
    repo = seed(client)
    url = "/api/admin/coverage/review.xlsx"
    assert client.get(url).status_code == 401
    client.post("/api/auth/login", json={"login": "user", "password": "user"})
    assert client.get(url).status_code == 403
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    response = client.get(url)
    workbook = load_workbook(BytesIO(response.content))
    try:
        rows = list(workbook.active.iter_rows())
        assert rows[0][7].value == DECISION
        assert [cell.value for cell in rows[1][:3]] == ["ru-software-17", "АВЗ.1", "=Demo"]
        assert rows[1][2].data_type == "s"
        assert rows[1][7].value is None
        assert rows[2][6].value == "Недостаточно данных"
    finally:
        workbook.close()
    result = client.post(
        "/api/admin/coverage/import?apply=true",
        files={"file": ("review.xlsx", response.content)},
    ).json()
    assert result["added"] == 0
    assert result["skipped"] == 2
    assert repo.get_item("ru-software-17").covers == ["ИАФ.3"]


def test_preview_invalid_and_confirmed_import(client):
    repo = seed(client)
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    rows = [
        (ITEM_CODE, REQUIREMENT_CODE, DECISION),
        ("ru-software-17", "АВЗ.1", "Принять"),
        ("ru-software-17", "АВЗ.1", "Принять"),
        ("vr", "АВЗ.1", "Отклонить"),
    ]
    assert upload(client, rows).json() == {
        "added": 1,
        "existing": 1,
        "skipped": 1,
        "error_count": 0,
        "errors": [],
        "applied": False,
    }
    broken = rows + [("ru-software-17", "unknown", "Принять"), ("org", "АВЗ.1", "Принять")]
    failure = upload(client, broken, apply=True).json()
    assert failure["error_count"] == 2 and not failure["applied"]
    assert repo.get_item("ru-software-17").covers == ["ИАФ.3"]
    assert upload(client, rows, apply=True).json()["added"] == 1
    assert upload(client, rows, apply=True).json()["added"] == 0
    assert repo.get_item("ru-software-17").covers == ["ИАФ.3", "АВЗ.1"]
    assert repo.get_item("vr").covers == []

    org = [(ITEM_CODE, REQUIREMENT_CODE), ("org", "ИАФ.3")]
    assert upload(client, org, kind="org", apply=True).json()["applied"]
    assert repo.get_item("org").covers == ["ИАФ.3"]
