import asyncio
import io

import httpx
import pytest
from openpyxl import load_workbook

from app.importers.prices import PriceResult, classify, collect_price
from app.importers.registry import RegistryImporter, RegistryRecord
from app.importers.registry_download import discover_exports
from app.importers.urls import normalize_urls


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "https://пример.рф/Прайс лист.pdf",
            "https://xn--e1afmkfd.xn--p1ai/%D0%9F%D1%80%D0%B0%D0%B9%D1%81%20%D0%BB%D0%B8%D1%81%D1%82.pdf",
        ),
        (
            "https://example.org/%D0%A6%D0%B5%D0%BD%D0%B0.pdf",
            "https://example.org/%D0%A6%D0%B5%D0%BD%D0%B0.pdf",
        ),
        ("https://example.org/a?one=1&amp;two=2", "https://example.org/a?one=1&two=2"),
        (
            "https://example.org/prices.php    (*Раздел 5 общего прайса-Аптека)",
            "https://example.org/prices.php",
        ),
        (
            "http://hhttps://example.org/prices.php       (Раздел 3 Производство)",
            "https://example.org/prices.php",
        ),
    ],
)
def test_url_normalization(raw, expected):
    assert normalize_urls(raw) == [expected]


def test_multiple_links_and_fragments():
    assert normalize_urls("https://example.org/one#price\nhttps://example.org/two") == [
        "https://example.org/one",
        "https://example.org/two",
    ]
    assert normalize_urls("javascript:alert(1)") == []


def test_product_price_is_not_workplace_count():
    html = (
        '<div class="product-price">1935 <span class="rub">Р</span></div>'
        "<p>Лицензия на 15 р.м. Дополнительная лицензия 15 р. м.</p>"
    )
    result = classify(html.encode())
    assert result.value == 1935
    assert result.parser_version == 2
    assert {candidate.amount for candidate in result.candidates} == {1935}
    assert classify("Лицензия на 15 р.м. для организаций".encode()).value is None


def test_explicit_product_price_precedes_unrelated_small_price():
    html = '<div class="product-price">1935 Р</div><p>Доставка 15 руб.</p>'
    assert classify(html.encode()).value == 1935
    assert classify("<p>Лицензия 1\u202f935,50 руб.</p>".encode()).value == 1935.5
    assert (
        classify("<p>Демо бесплатно. Стоимость уточняйте в отделе продаж.</p>".encode()).value
        is None
    )


def test_structured_rub_price():
    html = (
        '<script type="application/ld+json">{"@type":"Product","offers":'
        '{"price":"1935","priceCurrency":"RUB"}}</script>'
    )
    assert classify(html.encode()).value == 1935


def test_redirect_to_private_address_is_blocked(monkeypatch):
    monkeypatch.setattr(
        "app.importers.prices.socket.getaddrinfo",
        lambda host, port: [
            (2, 1, 6, "", ("93.184.216.34" if host == "example.org" else "127.0.0.1", port))
        ],
    )
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://localhost/private"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await collect_price(client, "https://example.org/prices")
            assert result.status == "error"
            assert len(requests) == 1

    asyncio.run(run())


def test_active_archive_sorting_and_excel(client):
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    store = client.app.state.registry.store
    store.upsert(
        [
            RegistryRecord(reg_number=1, name="Бета", owner="Я", cost_url="https://example.org/1"),
            RegistryRecord(reg_number=2, name="Альфа", owner="А", cost_url="https://example.org/2"),
            RegistryRecord(reg_number=3, name="Архив", exclusion_date="2026-01-01"),
        ]
    )
    store.save_price([1], PriceResult(status="ok", value=1935), "https://example.org/1")

    def ids(query):
        return [
            row["record"]["reg_number"]
            for row in client.get("/api/admin/registry?" + query).json()["items"]
        ]

    assert ids("") == [1, 2]
    assert ids("state=excluded") == [3]
    assert ids("sort=name") == [2, 1]
    assert ids("sort=name&direction=desc") == [1, 2]
    assert ids("sort=reg_number&direction=desc&limit=1") == [2]
    assert ids("sort=value&direction=desc") == [1, 2]
    assert client.get("/api/admin/registry?sort=invalid").status_code == 422
    response = client.get("/api/admin/registry/export.xlsx?sort=name")
    assert response.status_code == 200
    book = load_workbook(io.BytesIO(response.content))
    rows = list(book.active.values)
    assert [row[1] for row in rows[1:]] == ["Альфа", "Бета"]
    assert rows[2][4] == 1935
    assert book.active.auto_filter.ref == "A1:F3"
    book.close()


def test_official_xml_shape_and_dictionary(tmp_path):
    path = tmp_path / "source.xml"
    path.write_text(
        """<?xml version="1.0"?><xml><dictionaries><fields>
      <item code="name">Название</item></fields></dictionaries><registry>
      <item id="123"><registrationNumber>9</registrationNumber><name>Тест</name>
      <owner><name>Вендор</name><identificationNumber>123</identificationNumber></owner>
      <costLink>https://example.org/Цена.pdf</costLink><excluded>Да</excluded>
      <exclusionDate>2026-01-01</exclusionDate><softwareClass code="01.01"/></item>
      </registry></xml>""",
        encoding="utf-8",
    )
    records, errors = RegistryImporter().parse_records(path)
    assert errors == []
    assert len(records) == 1
    assert records[0].owner == "Вендор"
    assert records[0].to_item().in_ru_software_registry is False


def test_official_download_reports_certificate_error(client, monkeypatch):
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})

    def fail(target):
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr("app.api.app.download_registry_xml", fail)
    response = client.get("/api/admin/registry/download/xml")
    assert response.status_code == 502
    assert "Сертификат" in response.json()["detail"]


def test_discover_official_export_links_without_guessed_urls():
    content = (
        b'<a href="?download=html">Download HTML</a>'
        b'<a href="/download?type=xls">Export Excel</a>'
        b'<a href="https://other.example/export.xls">Export XLS</a>'
    )
    urls = discover_exports(content)
    assert urls["html"] == "https://reestr.digital.gov.ru/reestr/?download=html"
    assert urls["xls"] == "https://reestr.digital.gov.ru/download?type=xls"


def test_multiple_sources_continue_after_page_without_price(monkeypatch):
    async def fake_download(client, url):
        return (
            b'<div class="product-price">1935 RUB</div>'
            if url.endswith("two")
            else b"No price listed. Please contact sales."
        )

    monkeypatch.setattr("app.importers.prices.download", fake_download)

    async def run():
        async with httpx.AsyncClient() as client:
            result = await collect_price(client, "https://example.org/one\nhttps://example.org/two")
            assert result.value == 1935
            assert result.source_url == "https://example.org/two"

    asyncio.run(run())


def test_explicit_license_price_not_usage_fee():
    html = "<p>Лицензия на ПО: 200 000 руб.</p><p>Генерация: 15 руб. / 1 ролик</p>"
    assert classify(html.encode()).value == 200000


def test_zero_product_price():
    assert classify(b'<div class="product-price">0 RUB</div>').value == 0
