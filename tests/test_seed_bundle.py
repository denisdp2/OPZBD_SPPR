"""Тесты seed-данных: требования, оргмеры, профили обязательности."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# файл может лежать в seed/ или в data/ (data/ в .gitignore, там он добавлен через git add -f)
SEED = next(
    (
        p
        for p in (
            ROOT / "seed" / "seed_bundle.json",
            ROOT / "data" / "seed_bundle.json",
        )
        if p.exists()
    ),
    ROOT / "data" / "seed_bundle.json",
)


@pytest.fixture(scope="module")
def bundle():
    return json.loads(SEED.read_text(encoding="utf-8"))


def test_counts(bundle):
    assert len(bundle["requirements"]) == 115  # 96 мер + 19 мероприятий
    assert len(bundle["items"]) == 19
    assert {p["id"] for p in bundle["profiles"]} == {"K1", "K2", "K3"}


def test_profile_sizes_match_appendix_2(bundle):
    sizes = {p["id"]: len(p["mandatory"]) for p in bundle["profiles"]}
    assert sizes == {"K3": 82, "K2": 85, "K1": 85}


def test_profiles_contain_only_measures_not_org_activities(bundle):
    for p in bundle["profiles"]:
        assert not any(i.startswith("ОРГ.") for i in p["mandatory"]), p["id"]


def test_requirement_ids_unique(bundle):
    ids = [r["id"] for r in bundle["requirements"]]
    assert len(ids) == len(set(ids))


def test_requirements_have_required_fields(bundle):
    for r in bundle["requirements"]:
        assert r["id"] and r["group"] and r["title"]
        assert r["id"].startswith(r["group"] + ".")


def test_profiles_reference_existing_requirements(bundle):
    known = {r["id"] for r in bundle["requirements"]}
    for p in bundle["profiles"]:
        assert set(p["mandatory"]) <= known, p["id"]
        assert len(p["mandatory"]) == len(set(p["mandatory"])), p["id"]


def test_org_items_are_org_and_cover_existing_requirements(bundle):
    known = {r["id"] for r in bundle["requirements"]}
    ids = [i["id"] for i in bundle["items"]]
    assert len(ids) == len(set(ids))
    for item in bundle["items"]:
        assert item["kind"] == "org"
        assert item["covers"], item["id"]
        assert set(item["covers"]) <= known, item["id"]


def test_import_and_read_back(client):
    """Импорт бандла через API и чтение обратно (нужна фикстура client)."""
    assert (
        client.post(
            "/api/auth/login", json={"login": "admin", "password": "admin"}
        ).status_code
        == 200
    )
    with SEED.open("rb") as f:
        res = client.post(
            "/api/admin/import/bundle",
            files={"file": ("seed_bundle.json", f, "application/json")},
        )
    assert res.status_code == 200, res.text
    assert len(client.get("/api/requirements").json()) == 115
    assert len(client.get("/api/items", params={"kind": "org"}).json()) == 19
    assert {p["id"] for p in client.get("/api/profiles").json()} >= {"K1", "K2", "K3"}
