"""Загрузка выгрузок; исключение проверки сертификата ограничено хостом реестра."""

from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.importers.prices import tls_context

REGISTRY_EXPORT_URL = "https://reestr.digital.gov.ru/reestr/?export=registry"
MAX_EXPORT_BYTES = 250_000_000


def discover_exports(content: bytes) -> dict[str, str]:
    exports = {"xml": REGISTRY_EXPORT_URL}
    soup = BeautifulSoup(content, "html.parser")
    for anchor in soup.find_all("a", href=True):
        url = urljoin("https://reestr.digital.gov.ru/reestr/", anchor["href"])
        if urlsplit(url).hostname != "reestr.digital.gov.ru" or urlsplit(url).scheme != "https":
            continue
        label = (anchor.get_text(" ", strip=True) + " " + anchor["href"]).lower()
        if any(token in label for token in ("скач", "export", "download")):
            if "xls" in label or "excel" in label:
                exports["xls"] = url
            elif "html" in label:
                exports["html"] = url
    return exports


def download_registry_export(target: Path, format: str = "xml") -> Path:
    try:
        with httpx.Client(
            verify=tls_context(),
            mounts={
                "https://reestr.digital.gov.ru": httpx.HTTPTransport(verify=False),
            },
            timeout=httpx.Timeout(180, connect=15),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            url = REGISTRY_EXPORT_URL
            if format != "xml":
                page = client.get("https://reestr.digital.gov.ru/reestr/")
                page.raise_for_status()
                url = discover_exports(page.content).get(format)
                if url is None:
                    raise ValueError(
                        f"На сайте не найдена опубликованная ссылка выгрузки {format.upper()}"
                    )
            with client.stream("GET", url) as response:
                response.raise_for_status()
                total = 0
                with target.open("wb") as output:
                    for chunk in response.iter_bytes(65536):
                        total += len(chunk)
                        if total > MAX_EXPORT_BYTES:
                            raise ValueError("Выгрузка превышает 250 МБ")
                        output.write(chunk)
        with target.open("rb") as source:
            start = source.read(8192).lstrip(b"\xef\xbb\xbf \r\n\t")
        if format == "xml":
            if b"<html" in start.lower() or not (
                start.startswith(b"<?xml") or b"<registry" in start
            ):
                raise ValueError("Вместо XML сайт вернул страницу ошибки или проверки доступа")
        elif not (
            start.startswith((b"PK", b"\xd0\xcf\x11\xe0"))
            or b"<table" in start.lower()
            or b"urn:schemas-microsoft-com:office:spreadsheet" in start
        ):
            raise ValueError("Вместо таблицы сайт вернул страницу ошибки или проверки доступа")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def download_registry_xml(target: Path) -> Path:
    return download_registry_export(target, "xml")
