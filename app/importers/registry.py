"""Разбор Excel-выгрузки реестра российского ПО без доступа к БД и сети."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from io import BytesIO
from itertools import chain
from pathlib import Path
from xml.etree import ElementTree

import xlrd
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from pydantic import BaseModel, Field, field_validator

from app.core.interfaces import Importer
from app.core.models import DataBundle, Item

COLUMNS = {
    "Регистрационный номер": "reg_number",
    "Наименование ПО": "name",
    "Альтернативные названия ПО": "alt_names",
    "Класс ПО": "software_class",
    "Код продукции": "okpd",
    "Дата исключения": "exclusion_date",
    "Сайт с документацией по установке и эксплуатации ПО": "docs_url",
    "Наименование (ФИО) правообладателя": "owner",
    "Идентификационный номер (ИНН)": "inn",
    "Ссылка на решения уполномоченного органа о включении сведений о ПО": "decision_url",
    "Ссылка на стоимость": "cost_url",
}


class RegistryRecord(BaseModel):
    reg_number: int = Field(gt=0)
    name: str = Field(default="", min_length=1, validate_default=True)
    alt_names: str = ""
    software_class: str = ""
    okpd: str = ""
    exclusion_date: str = ""
    docs_url: str = ""
    owner: str = ""
    inn: str = ""
    decision_url: str = ""
    cost_url: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value, info):
        name = str(value or "").replace("\xa0", " ").strip()
        return name or f"Запись №{info.data.get('reg_number', '?')} (без наименования)"

    @field_validator("exclusion_date", mode="before")
    @classmethod
    def normalize_date(cls, value):
        value = str(value or "").strip()
        for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:10], pattern).date().isoformat()
            except ValueError:
                continue
        return value

    def to_item(self) -> Item:
        return Item(
            id=f"ru-software-{self.reg_number}",
            kind="tool",
            name=self.name,
            vendor=self.owner,
            in_ru_software_registry=not bool(self.exclusion_date),
            description="\n".join(filter(None, [self.software_class, self.alt_names])),
        )


class RegistryImporter(Importer):
    name = "ru-software"
    title = "Реестр российского ПО"
    target = "items"
    extensions = (".xlsx", ".xls", ".xml", ".json")

    def parse_records(self, path: Path) -> tuple[list[RegistryRecord], list[str]]:
        if path.suffix.lower() == ".xml":
            return self.parse_xml(path)
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                payload = payload.get("records")
            if not isinstance(payload, list):
                raise ValueError("JSON должен содержать список записей реестра")
            records, errors, seen = [], [], set()
            for index, entry in enumerate(payload, 1):
                try:
                    record = RegistryRecord.model_validate(entry)
                    if record.reg_number in seen:
                        raise ValueError(f"повтор номера {record.reg_number}")
                    records.append(record)
                    seen.add(record.reg_number)
                except ValueError as exc:
                    errors.append(f"Запись {index}: {exc}")
            return records, errors
        with path.open("rb") as source:
            signature = source.read(8)
        if signature.startswith(b"PK"):
            records, errors, _ = self.read_xlsx(path)
            return records, errors
        if path.suffix.lower() == ".xls":
            if signature.startswith(b"\xd0\xcf\x11\xe0"):
                try:
                    book = xlrd.open_workbook(file_contents=path.read_bytes(), on_demand=True)
                except xlrd.XLRDError as exc:
                    raise ValueError("Не удалось прочитать XLS") from exc
                try:
                    return self.parse_rows(book.sheet_by_index(0).get_rows(), xls_cells=True)
                finally:
                    book.release_resources()
            content = path.read_bytes()
            if b"urn:schemas-microsoft-com:office:spreadsheet" in content[:8192]:
                namespace = "{urn:schemas-microsoft-com:office:spreadsheet}"
                if b"<!DOCTYPE" in content.upper():
                    raise ValueError("XML с DTD не поддерживается")
                root = ElementTree.parse(BytesIO(content))
                return self.parse_rows(
                    [cell.findtext(namespace + "Data") for cell in row]
                    for row in root.iter(namespace + "Row")
                )
            soup = BeautifulSoup(content, "html.parser")
            return self.parse_rows(
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in soup.find_all("tr")
            )
        raise ValueError("Не удалось прочитать Excel")

    def read_xlsx(self, path: Path) -> tuple[list[RegistryRecord], list[str], str | None]:
        with path.open("rb") as source:
            book = load_workbook(source, read_only=True, data_only=True)
            try:
                rows = book.active.iter_rows(values_only=True)
                first_row = next(rows, ())
                records, errors = self.parse_rows(chain((first_row,), rows))
            finally:
                book.close()
        source_date = None
        if len(first_row) > 2 and str(first_row[0]).strip() == "Дата:":
            try:
                source_date = datetime.strptime(str(first_row[2]).strip(), "%H:%M:%S %d.%m.%Y")
            except ValueError:
                pass
        return records, errors, source_date.date().isoformat() if source_date else None

    def parse_rows(self, source, *, xls_cells=False):
        records, errors, seen = [], [], set()
        if xls_cells:
            source = ([cell.value for cell in row] for row in source)
        rows = enumerate(source, 1)
        indices = {}
        for number, row in rows:
            for index, value in enumerate(row):
                header = " ".join(str(value or "").split())
                for title, key in COLUMNS.items():
                    if header.startswith(title[:40]):
                        indices[key] = index
            if "reg_number" in indices and "name" in indices:
                break
            if number >= 30:
                raise ValueError("Не найдены заголовки регистрационного номера и наименования ПО")
        if not {"reg_number", "name"} <= indices.keys():
            raise ValueError("Пустая выгрузка или отсутствуют обязательные столбцы")
        for number, row in rows:
            values = {
                key: str(row[i]).strip() if i < len(row) and row[i] is not None else ""
                for key, i in indices.items()
            }
            raw = values.get("reg_number", "")
            if not raw:
                continue
            if not values.get("name") and re.match(r"№\s*\d+\s*[-–—]\s*Классификатор\b", raw):
                continue
            try:
                # Excel может хранить целые номера в числовых ячейках.
                reg = int(raw[:-2] if raw.endswith(".0") else raw)
                if reg in seen:
                    raise ValueError(f"повтор номера {reg}")
                values["reg_number"] = reg
                record = RegistryRecord(**values)
                records.append(record)
                seen.add(reg)
            except ValueError as exc:
                errors.append(f"Строка {number}: {exc}")
        return records, errors

    def parse_xml(self, path: Path) -> tuple[list[RegistryRecord], list[str]]:
        records, errors, _ = self.read_xml(path)
        return records, errors

    def read_xml(self, path: Path) -> tuple[list[RegistryRecord], list[str], str | None]:
        with path.open("rb") as source:
            if b"<!DOCTYPE" in source.read(8192).upper():
                raise ValueError("XML с DTD не поддерживается")
        records, errors, seen = [], [], set()
        source_date = None
        for event, element in ElementTree.iterparse(path, events=("start", "end")):
            if event == "start":
                if element.tag == "registry" and (generated := element.get("genDate")):
                    for pattern in ("%Y.%m.%d", "%Y-%m-%d", "%d.%m.%Y"):
                        try:
                            source_date = datetime.strptime(generated[:10], pattern).date()
                            break
                        except ValueError:
                            continue
                continue
            if element.tag != "item" or element.find("registrationNumber") is None:
                continue

            def text(tag, node=element):
                return html.unescape((node.findtext(tag) or "").strip())

            try:
                number = int(text("registrationNumber"))
                if number in seen:
                    raise ValueError(f"Повтор номера {number}")
                excluded = text("excluded").casefold() in {"да", "true", "1"}
                records.append(
                    RegistryRecord(
                        reg_number=number,
                        name=text("name"),
                        alt_names="; ".join(
                            html.unescape(e.text or "")
                            for e in element.findall("previousAlternativeName")
                        ),
                        owner="; ".join(
                            html.unescape(e.text or "") for e in element.findall("owner/name")
                        ),
                        inn="; ".join(
                            e.text or "" for e in element.findall("owner/identificationNumber")
                        ),
                        software_class="; ".join(
                            e.get("code", "") for e in element.findall("softwareClass")
                        ),
                        okpd="; ".join(e.get("code", "") for e in element.findall("codeOkpd")),
                        docs_url=text("descriptionLink"),
                        cost_url=text("costLink"),
                        exclusion_date=text("exclusionDate")
                        or ("Дата не указана" if excluded else ""),
                    )
                )
                seen.add(number)
            except ValueError as exc:
                errors.append(f"Запись {text('registrationNumber')}: {exc}")
            element.clear()
        if not records:
            raise ValueError("В XML не найдены записи реестра")
        return records, errors, source_date.isoformat() if source_date else None

    def parse(self, path: Path) -> tuple[DataBundle, list[str]]:
        records, errors = self.parse_records(path)
        return DataBundle(items=[record.to_item() for record in records]), errors
