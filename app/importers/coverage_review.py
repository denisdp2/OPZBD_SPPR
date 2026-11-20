"""Предложения по покрытию и обмен таблицами проверки."""

import re
from collections.abc import Iterable
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell

from app.core.models import Item, Requirement

ITEM_CODE = "Код позиции"
REQUIREMENT_CODE = "Код требования"
DECISION = "Решение"
MAX_FILE_SIZE = 12_000_000
MAX_ROWS = 150_000
CLASS_RULES = {
    "03.02": ("РСБ.1", "РСБ.2"),
    "03.03": ("МСЭ.3",),
    "03.06": ("АВЗ.1",),
    "03.11": ("ЗКС.1",),
    "03.12": ("УПД.2",),
}
TEXT_RULES = [
    ("ИАФ.1", r"индивидуальн\w* уч[её]тн\w* запис\w*|идентификац\w* пользовател\w*"),
    ("ИАФ.3", r"аутентификац\w* пользовател\w*|вход по парол\w*"),
    ("УПД.2", r"разграничени\w* прав доступа|ролев\w* модел\w* доступа"),
    ("УПД.3", r"управлени\w* уч[её]тн\w* записями"),
    ("РСБ.1", r"(?:регистрац\w*|журнал\w*) событий безопасности|журнал\w* входов"),
    ("АВЗ.1", r"антивирус\w* защит\w*|\bантивирус\b"),
    ("МСЭ.3", r"межсетев\w* экран\w*|\bfirewall\b"),
    ("ЗКС.1", r"шифровани\w* трафика|шифровани\w* данных при передач\w*"),
]
TEXT_RULES = [(code, re.compile(pattern, re.I)) for code, pattern in TEXT_RULES]


def suggest_coverage(
    items: Iterable[Item], requirements: dict[str, Requirement], records: dict[str, dict]
) -> Iterable[tuple]:
    for item in items:
        existing = set(item.covers)
        record = records.get(item.id, {})
        if record.get("exclusion_date"):
            continue
        evidence = {}
        for code, pattern in TEXT_RULES:
            for field, value in (("Название", item.name), ("Описание", item.description)):
                if match := pattern.search(value):
                    evidence[code] = f"{field}: {match.group()}"
                    break
        for class_code in re.findall(
            r"(?<!\d)\d{2}\.\d{2}(?!\d)", record.get("software_class", "")
        ):
            for code in CLASS_RULES.get(class_code, ()):
                evidence.setdefault(code, f"Класс ПО {class_code}; проверьте функции продукта")
        candidates = {
            code: reason
            for code, reason in evidence.items()
            if code in requirements and code not in existing
        }
        if candidates:
            for code, reason in candidates.items():
                yield (
                    item.id,
                    code,
                    item.name,
                    requirements[code].title,
                    reason,
                    record.get("docs_url", ""),
                    "На проверку",
                )
        else:
            status = "Связи уже есть" if existing else "Недостаточно данных"
            yield item.id, "", item.name, "", "", record.get("docs_url", ""), status


def review_workbook(rows: Iterable[tuple]) -> bytes:
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Соответствия")
    sheet.freeze_panes = "C2"
    for column, width in zip("ABCDEFGH", (24, 20, 55, 45, 55, 45, 25, 20), strict=True):
        sheet.column_dimensions[column].width = width
    sheet.append(
        (
            ITEM_CODE,
            REQUIREMENT_CODE,
            "Название позиции",
            "Требование",
            "Основание",
            "Документация",
            "Статус",
            DECISION,
        )
    )
    last_row = 1
    for row in rows:
        last_row += 1
        # Registry names and descriptions are data, including values beginning with "=".
        cells = []
        for value in row:
            cell = WriteOnlyCell(sheet, value=value)
            cell.data_type = "s"
            cells.append(cell)
        sheet.append(cells)
    sheet.auto_filter.ref = f"A1:H{last_row}"
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def read_review(content: bytes) -> tuple[list[tuple[int, str, str]], int, list[str]]:
    with ZipFile(BytesIO(content)) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > 128_000_000:
            raise ValueError("Слишком большой файл Excel после распаковки")
    book = load_workbook(BytesIO(content), read_only=True, keep_links=False)
    try:
        rows = book.worksheets[0].iter_rows(max_col=16)
        headers = next(rows, ())
        names = [str(c.value or "").strip().casefold() for c in headers]
        if any(names.count(name.casefold()) != 1 for name in (ITEM_CODE, REQUIREMENT_CODE)):
            raise ValueError(f"В первой строке нужны столбцы «{ITEM_CODE}» и «{REQUIREMENT_CODE}»")
        if names.count(DECISION.casefold()) > 1 or (
            "статус" in names and DECISION.casefold() not in names
        ):
            raise ValueError("В таблице проверки нужен один столбец «Решение»")
        item_col = names.index(ITEM_CODE.casefold())
        req_col = names.index(REQUIREMENT_CODE.casefold())
        decision_col = names.index(DECISION.casefold()) if DECISION.casefold() in names else None
        links, skipped, errors = [], 0, []
        for number, cells in enumerate(rows, 2):
            if number > MAX_ROWS + 1:
                raise ValueError("В файле не должно быть больше 150 000 строк")
            if not any(c.value is not None for c in cells):
                continue
            relevant = [cells[item_col], cells[req_col]]
            if decision_col is not None:
                relevant.append(cells[decision_col])
            if any(c.data_type == "f" for c in relevant):
                errors.append(f"Строка {number}: используйте значения вместо формул")
                continue
            if decision_col is not None:
                decision = str(cells[decision_col].value or "").strip().casefold()
                if decision in {"", "отклонить", "нет"}:
                    skipped += 1
                    continue
                if decision not in {"принять", "да"}:
                    errors.append(f"Строка {number}: решение должно быть «Принять» или «Отклонить»")
                    continue
            item, requirement = (str(c.value or "").strip() for c in relevant[:2])
            if not item or not requirement:
                errors.append(f"Строка {number}: заполните коды позиции и требования")
            else:
                links.append((number, item, requirement))
        return links, skipped, errors
    finally:
        book.close()
