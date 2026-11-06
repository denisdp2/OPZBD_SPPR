import asyncio
import io
import sqlite3
import zipfile

import httpx
import pytest
from openpyxl import Workbook

from app.core.models import Item, Requirement
from app.importers.prices import PriceResult, classify, collect_price
from app.importers.registry import RegistryImporter, RegistryRecord
from app.storage.registry import RegistryStore
from app.storage.sqlite import SQLiteRepository


def workbook(rows):
    book = Workbook()
    sheet = book.active
    sheet.append(["Экспорт реестра"])
    sheet.append([])
    sheet.append(
        [
            "Регистрационный номер",
            "Наименование ПО",
            "Класс ПО",
            "Наименование (ФИО) правообладателя",
            "Ссылка на стоимость",
            "Дата исключения",
        ]
    )
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def login(client):
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})


def upload(client, data):
    return client.post("/api/admin/import/ru-software", files={"file": ("registry.xlsx", data)})


def test_import_roundtrip_and_preserve_manual_fields(client):
    login(client)
    data = workbook([[42, "Защита", "Антивирус", "Вендор", "https://example.org/prices", None]])
    assert upload(client, data).json()["imported"] == 1
    item = client.get("/api/admin/items/ru-software-42").json()
    assert item["name"] == "Защита"
    assert item["in_ru_software_registry"] is True
    item.update(
        covers=["ИАФ.1"], fstec_certified=True, fstec_cert_no="123", description="Моя заметка"
    )
    assert client.put("/api/admin/items/ru-software-42", json=item).status_code == 200
    store = client.app.state.registry.store
    store.save_price([42], PriceResult(status="ok", value=100), "https://example.org/prices")
    assert upload(client, data).json()["imported"] == 1
    fresh = client.get("/api/admin/items/ru-software-42").json()
    assert fresh["covers"] == ["ИАФ.1"]
    assert fresh["fstec_cert_no"] == "123"
    assert fresh["description"] == "Моя заметка"
    assert client.get("/api/admin/registry").json()["items"][0]["price"]["value"] == 100
    changed = workbook(
        [[42, "Новое имя", "Антивирус", "Вендор", "https://example.org/new", "2026-01-01"]]
    )
    assert upload(client, changed).status_code == 200
    assert client.get("/api/admin/items/ru-software-42").json()["in_ru_software_registry"] is False
    assert client.get("/api/admin/registry?state=all").json()["items"][0]["price"] is None
    assert client.get("/api/admin/registry?state=excluded&q=Новое").json()["total"] == 1
    assert client.get("/api/admin/registry?q=нет").json()["total"] == 0
    assert len(client.get("/api/admin/export").json()["items"]) == 1


def test_parser_reports_bad_rows(tmp_path):
    path = tmp_path / "input.xlsx"
    path.write_bytes(workbook([[7, "ПО"], [7, "Дубликат"], ["bad", "Ошибка"], [8, ""]]))
    bundle, errors = RegistryImporter().parse(path)
    assert len(bundle.items) == 1
    assert len(errors) == 3


def test_registry_routes_require_admin(client):
    data = workbook([[1, "ПО"]])
    assert upload(client, data).status_code == 401
    assert client.get("/api/admin/registry").status_code == 401
    client.post("/api/auth/login", json={"login": "user", "password": "user"})
    assert upload(client, data).status_code == 403
    assert client.post("/api/admin/registry/prices").status_code == 403


def test_invalid_upload_and_id_mismatch(client):
    login(client)
    assert upload(client, b"not an xlsx").status_code == 422
    response = client.post("/api/admin/import/unknown", files={"file": ("a.xlsx", b"bad")})
    assert response.status_code == 404
    item = Item(id="one", kind="tool", name="Test").model_dump()
    assert client.put("/api/admin/items/two", json=item).status_code == 422
    assert client.get("/api/admin/items/missing").status_code == 404


@pytest.mark.parametrize(
    "text,status,value",
    [
        ("Стоимость лицензии: 12 500,50 руб. Тариф: 2 тыс. руб.", "ok", 2000),
        ("Лицензия предоставляется бесплатно", "free", 0),
        ("Open source: стоимость лицензии обсуждается индивидуально", "no_price", None),
        ("Цена 0 руб.", "free", 0),
        ("Уточните стоимость лицензии в отделе продаж поставщика", "no_price", None),
    ],
)
def test_price_classification(text, status, value):
    result = classify(text.encode())
    assert result.status == status
    assert result.value == value


def test_docx_and_html_prices():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", "<document><p>Цена 1234 руб.</p></document>")
    assert classify(output.getvalue()).value == 1234
    assert classify(b"<script>100 rub</script><p>License price 250 rub</p>").value == 250
    assert classify(b"%PDF-invalid").status == "error"


def test_price_download_blocks_local_addresses():
    async def run():
        async with httpx.AsyncClient() as client:
            result = await collect_price(client, "http://127.0.0.1/private")
            assert result.status == "error"
            assert "адреса запрещены" in result.note

    asyncio.run(run())


def test_price_job_deduplicates_and_retries(client, monkeypatch):
    login(client)
    data = workbook(
        [
            [1, "Один", "", "", "https://example.org/prices"],
            [2, "Два", "", "", "https://example.org/prices"],
            [3, "Исключён", "", "", "https://example.org/old", "2025-01-01"],
        ]
    )
    upload(client, data)
    calls = []

    async def fake_collect(client, url):
        calls.append(url)
        return PriceResult(status="error", note="Тестовая ошибка", parser_version=2)

    monkeypatch.setattr("app.importers.service.collect_price", fake_collect)
    assert client.post("/api/admin/registry/prices").json()["total"] == 1
    assert len(calls) == 1
    assert client.get("/api/admin/registry/prices/status").json()["done"] == 1
    assert client.post("/api/admin/registry/prices").json()["total"] == 0
    assert client.post("/api/admin/registry/prices?retry=true").json()["total"] == 1
    assert len(calls) == 2


def test_storage_persistence_and_gaps(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    repo = SQLiteRepository(path)
    repo.upsert_requirement(Requirement(id="R1", title="Первое"))
    repo.upsert_requirement(Requirement(id="R2", title="Второе"))
    repo.upsert_item(Item(id="tool", kind="tool", name="ПО", covers=["R1"]))
    assert [req.id for req in SQLiteRepository(path).uncovered_requirements()] == ["R2"]
    store = RegistryStore(path)
    store.upsert([RegistryRecord(reg_number=1, name="ПО", cost_url="https://example.org/new")])
    store.save_price([1], PriceResult(status="ok", value=99), "https://example.org/old")
    assert store.list_records()[0]["price"] is None


def test_legacy_database_upload_restores_prices(client, tmp_path):
    login(client)
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as con:
        con.execute(
            "CREATE TABLE software (reg_number INTEGER, name, class, owner, cost_url, "
            "cost_status, cost_value, cost_note)"
        )
        con.execute(
            "INSERT INTO software VALUES (1, 'Защита', 'Класс', 'Вендор', "
            "'https://example.org/prices', 'ok', 1500, 'pdf')"
        )
        con.execute("CREATE TABLE cost_candidates(reg_number INTEGER, amount REAL, context TEXT)")
        con.execute("INSERT INTO cost_candidates VALUES (1, 1500, 'Лицензия 1500 руб.')")
    before = source.read_bytes()
    response = client.post(
        "/api/admin/import/ru-software-sqlite", files={"file": ("legacy.db", before)}
    )
    assert response.status_code == 200
    assert response.json()["imported"] == 1
    entry = client.get("/api/admin/registry").json()["items"][0]
    assert entry["price"]["value"] == 1500
    assert entry["price"]["candidates"][0]["context"] == "Лицензия 1500 руб."
    assert source.read_bytes() == before


def test_new_record_reuses_known_url_result(client, monkeypatch):
    login(client)
    upload(client, workbook([[1, "Один", "", "", "https://example.org/prices"]]))
    client.app.state.registry.store.save_price(
        [1], PriceResult(status="ok", value=125, parser_version=2), "https://example.org/prices"
    )
    upload(client, workbook([[2, "Два", "", "", "https://example.org/prices"]]))

    async def unexpected_download(*args):
        pytest.fail("Повторное скачивание уже обработанной ссылки")

    monkeypatch.setattr("app.importers.service.collect_price", unexpected_download)
    assert client.post("/api/admin/registry/prices").json()["total"] == 0
    entries = client.get("/api/admin/registry").json()["items"]
    assert [entry["price"]["value"] for entry in entries] == [125, 125]


def test_json_bundle_roundtrip(client):
    login(client)
    bundle = {
        "requirements": [{"id": "R1", "title": "Требование"}],
        "items": [{"id": "tool", "kind": "tool", "name": "СЗИ", "covers": ["R1"]}],
        "profiles": [{"id": "p1", "name": "Профиль", "mandatory": ["R1"]}],
    }
    import json

    result = client.post(
        "/api/admin/import/bundle", files={"file": ("bundle.json", json.dumps(bundle).encode())}
    )
    assert result.json()["imported"] == 3
    assert client.get("/api/admin/gaps").json() == []
    exported = client.get("/api/admin/export").json()
    assert exported["profiles"][0]["mandatory"] == ["R1"]
    assert exported["items"][0]["covers"] == ["R1"]
