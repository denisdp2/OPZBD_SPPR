"""Excel-экспорт текущего отфильтрованного реестра."""

import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


def export_registry_xlsx(rows: list[dict]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Реестр ПО"
    sheet.append(
        [
            "Регистрационный номер",
            "Наименование ПО",
            "Правообладатель",
            "Статус",
            "Стоимость, руб.",
            "Источник",
        ]
    )
    for row_number, entry in enumerate(rows, 2):
        record, price = entry["record"], entry["price"]
        value = price["value"] if price and price["status"] in {"ok", "free"} else None
        values = [
            record["reg_number"],
            record["name"],
            record["owner"],
            "Исключено: " + record["exclusion_date"] if record["exclusion_date"] else "В реестре",
            value,
            entry.get("source_url") or "",
        ]
        for column_number, value in enumerate(values, 1):
            cell = sheet.cell(row_number, column_number, value)
            # Текст из внешнего реестра не должен становиться формулой Excel.
            if isinstance(cell.value, str):
                cell.data_type = "s"
        sheet.cell(row_number, 5).number_format = "#,##0.00"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="15344C")
    for column, width in zip("ABCDEF", [24, 65, 60, 27, 22, 75], strict=True):
        sheet.column_dimensions[column].width = width
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()
