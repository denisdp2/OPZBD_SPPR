"""Чтение результатов прежних скриптов. Исходная SQLite-база открывается только для чтения."""

import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from app.core.interfaces import Importer
from app.core.models import DataBundle
from app.importers.prices import PriceCandidate, PriceResult
from app.importers.registry import RegistryRecord


class LegacyRegistryImporter(Importer):
    name = "ru-software-sqlite"
    title = "База реестра из прежних скриптов"
    target = "items"
    extensions = (".db", ".sqlite", ".sqlite3")

    def read_source(self, path: Path):
        records, results, errors = [], {}, []
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            columns = {row[1] for row in con.execute("PRAGMA table_info(software)")}
            if not {"reg_number", "name"} <= columns:
                raise ValueError("В базе нет таблицы software с номером и наименованием ПО")
            candidates = defaultdict(list)
            if con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cost_candidates'"
            ).fetchone():
                for row in con.execute("SELECT reg_number, amount, context FROM cost_candidates"):
                    try:
                        if len(candidates[row[0]]) < 30:
                            candidates[row[0]].append(
                                PriceCandidate(amount=row[1], context=row[2] or "")
                            )
                    except ValidationError:
                        continue
            for row in con.execute("SELECT * FROM software ORDER BY reg_number"):
                values = dict(row)
                number = values.get("reg_number")
                try:
                    fields = {
                        key: values.get("class" if key == "software_class" else key) or ""
                        for key in RegistryRecord.model_fields
                        if key != "reg_number"
                    }
                    fields = {key: str(value).strip() for key, value in fields.items()}
                    record = RegistryRecord(reg_number=number, **fields)
                    records.append(record)
                    if values.get("cost_status"):
                        results[record.reg_number] = PriceResult(
                            status=values["cost_status"],
                            value=values.get("cost_value"),
                            note=values.get("cost_note") or "",
                            candidates=candidates[record.reg_number],
                        )
                except (ValueError, TypeError) as exc:
                    errors.append(f"Запись {number}: {exc}")
        return records, results, errors

    def parse(self, path: Path):
        records, _, errors = self.read_source(path)
        return DataBundle(items=[record.to_item() for record in records]), errors
