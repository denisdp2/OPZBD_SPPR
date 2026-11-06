"""Разбор Excel-выгрузки реестра российского ПО без доступа к БД и сети."""

import html
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

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
    name: str = Field(min_length=1)
    alt_names: str = ""
    software_class: str = ""
    okpd: str = ""
    exclusion_date: str = ""
    docs_url: str = ""
    owner: str = ""
    inn: str = ""
    decision_url: str = ""
    cost_url: str = ""

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
    extensions = (".xlsx", ".xml")

    def parse_records(self, path: Path) -> tuple[list[RegistryRecord], list[str]]:
        if path.suffix.lower() == ".xml":
            return self.parse_xml(path)
        book = load_workbook(path, read_only=True, data_only=True)
        records, errors, seen = [], [], set()
        try:
            rows = enumerate(book.active.iter_rows(values_only=True), 1)
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
                    raise ValueError(
                        "Не найдены заголовки регистрационного номера и наименования ПО"
                    )
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
                try:
                    # Excel может хранить целые номера в числовых ячейках.
                    reg = int(raw.removesuffix(".0"))
                    if reg in seen:
                        raise ValueError(f"повтор номера {reg}")
                    values["reg_number"] = reg
                    record = RegistryRecord(**values)
                    records.append(record)
                    seen.add(reg)
                except ValueError as exc:
                    errors.append(f"Строка {number}: {exc}")
            return records, errors
        finally:
            book.close()

    def parse_xml(self, path: Path) -> tuple[list[RegistryRecord], list[str]]:
        with path.open("rb") as source:
            if b"<!DOCTYPE" in source.read(8192).upper():
                raise ValueError("XML с DTD не поддерживается")
        records, errors, seen = [], [], set()
        for _, element in ElementTree.iterparse(path, events=("end",)):
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
                errors.append(str(exc))
            element.clear()
        if not records:
            raise ValueError("В XML не найдены записи реестра")
        return records, errors

    def parse(self, path: Path) -> tuple[DataBundle, list[str]]:
        records, errors = self.parse_records(path)
        return DataBundle(items=[record.to_item() for record in records]), errors
