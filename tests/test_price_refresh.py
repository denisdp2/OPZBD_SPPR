from app.importers.prices import PARSER_VERSION, PriceResult
from app.importers.registry import RegistryRecord


def test_refresh_processes_all_250_links_in_batches(client, monkeypatch):
    store = client.app.state.registry.store
    records = [
        RegistryRecord(reg_number=n, name=f"ПО {n}", cost_url=f"https://example.org/{n}")
        for n in range(1, 251)
    ]
    records.extend(
        [
            RegistryRecord(reg_number=251, name="Общая ссылка", cost_url="https://example.org/1"),
            RegistryRecord(reg_number=252, name="Без ссылки"),
            RegistryRecord(
                reg_number=253,
                name="Исключено",
                cost_url="https://example.org/excluded",
                exclusion_date="2026-01-01",
            ),
        ]
    )
    store.upsert(records)
    store.restore_prices(
        {
            record.reg_number: PriceResult(status="ok", value=10, parser_version=PARSER_VERSION)
            for record in records
        }
    )
    calls, saved = [], set()
    original_save = store.save_price

    def save(numbers, result, url):
        original_save(numbers, result, url)
        saved.add(int(url.rsplit("/", 1)[1]))

    async def collect(client, url):
        number = int(url.rsplit("/", 1)[1])
        # Следующая порция начинается после сохранения всей предыдущей.
        if number > 100:
            assert set(range(1, 101)) <= saved
        if number > 200:
            assert set(range(1, 201)) <= saved
        calls.append(number)
        if number == 125:
            return PriceResult(status="error", note="Недоступен", parser_version=PARSER_VERSION)
        return PriceResult(status="ok", value=number + 1000, parser_version=PARSER_VERSION)

    monkeypatch.setattr(store, "save_price", save)
    monkeypatch.setattr("app.importers.service.collect_price", collect)
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    response = client.post("/api/admin/registry/prices?refresh=true&limit=100")
    assert response.status_code == 202
    assert response.json()["total"] == 250
    assert sorted(calls) == list(range(1, 251))
    assert client.get("/api/admin/registry/prices/status").json() == {
        "status": "completed",
        "total": 250,
        "done": 250,
        "errors": 1,
    }
    results = {entry["record"]["reg_number"]: entry["price"] for entry in store.list_records()}
    assert results[250]["value"] == 1250
    assert results[251]["value"] == results[1]["value"] == 1001
    assert results[125]["status"] == "error"
    assert results[253]["value"] == 10


def test_normal_collection_still_limits_each_run_and_continues(client, monkeypatch):
    store = client.app.state.registry.store
    store.upsert(
        [
            RegistryRecord(reg_number=n, name=f"ПО {n}", cost_url=f"https://example.org/{n}")
            for n in range(1, 251)
        ]
    )
    calls = []

    async def collect(client, url):
        calls.append(url)
        return PriceResult(status="ok", value=100, parser_version=PARSER_VERSION)

    monkeypatch.setattr("app.importers.service.collect_price", collect)
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    for expected in (100, 100, 50, 0):
        response = client.post("/api/admin/registry/prices?limit=100")
        assert response.json()["total"] == expected
    assert len(calls) == len(set(calls)) == 250
