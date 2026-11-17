"""Метаданные реестра и цены отделены от общего контракта Item."""

import sqlite3
from contextlib import closing
from pathlib import Path

from app.importers.prices import PriceResult
from app.importers.registry import RegistryRecord
from app.importers.urls import canonical_links, source_url


class RegistryStore:
    def __init__(self, path: Path):
        self.path = path
        with closing(sqlite3.connect(path)) as con, con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS registry "
                "(reg_number INTEGER PRIMARY KEY, data TEXT NOT NULL, "
                "price TEXT, manual_price REAL)"
            )

            columns = {row[1] for row in con.execute("PRAGMA table_info(registry)")}
            if "manual_price" not in columns:
                con.execute("ALTER TABLE registry ADD COLUMN manual_price REAL")

    def set_manual_price(self, number: int, value: float | None) -> bool:
        with closing(sqlite3.connect(self.path)) as con, con:
            cursor = con.execute(
                "UPDATE registry SET manual_price=? WHERE reg_number=?", (value, number)
            )
            return cursor.rowcount > 0

    def upsert(self, records: list[RegistryRecord]) -> None:
        with closing(sqlite3.connect(self.path)) as con, con:
            for record in records:
                old = con.execute(
                    "SELECT data FROM registry WHERE reg_number=?", (record.reg_number,)
                ).fetchone()
                changed = (
                    old and RegistryRecord.model_validate_json(old[0]).cost_url != record.cost_url
                )
                con.execute(
                    "INSERT INTO registry(reg_number, data) VALUES (?, ?) "
                    "ON CONFLICT(reg_number) DO UPDATE SET data=excluded.data",
                    (record.reg_number, record.model_dump_json()),
                )
                if changed:
                    con.execute(
                        "UPDATE registry SET price=NULL WHERE reg_number=?", (record.reg_number,)
                    )

    def list_records(self) -> list[dict]:
        with closing(sqlite3.connect(self.path)) as con:
            return [
                dict(
                    record=RegistryRecord.model_validate_json(data).model_dump(),
                    price=PriceResult.model_validate_json(price).model_dump() if price else None,
                    manual_price=manual_price,
                )
                for data, price, manual_price in con.execute(
                    "SELECT data, price, manual_price FROM registry ORDER BY reg_number"
                )
            ]

    def query(self, q="", state="active", sort="reg_number", descending=False) -> list[dict]:
        rows = self.list_records()
        if state != "all":
            rows = [
                row
                for row in rows
                if bool(row["record"]["exclusion_date"]) == (state == "excluded")
            ]
        if q:
            q = q.casefold()
            rows = [
                row
                for row in rows
                if q
                in " ".join(
                    str(row["record"][key]) for key in ("reg_number", "name", "owner")
                ).casefold()
            ]
        for row in rows:
            if row["manual_price"] is not None:
                row["price"] = PriceResult(status="ok", value=row["manual_price"]).model_dump()
            row["source_url"] = source_url(
                (row["price"] or {}).get("source_url") or row["record"]["cost_url"]
            )

        def key(row):
            if sort == "value":
                price = row["price"]
                return price["value"] if price and price["status"] in {"ok", "free"} else None
            if sort == "source":
                return row["source_url"] or ""
            if sort == "status":
                return row["record"]["exclusion_date"]
            value = row["record"].get(sort, row["record"]["reg_number"])
            return value.casefold().replace("ё", "е") if isinstance(value, str) else value

        # Пустые цены всегда в конце, независимо от направления сортировки.
        known = [row for row in rows if key(row) is not None]
        unknown = [row for row in rows if key(row) is None]
        return sorted(known, key=key, reverse=descending) + unknown

    def save_price(self, numbers: list[int], result: PriceResult, url: str) -> None:
        with closing(sqlite3.connect(self.path)) as con, con:
            for number in numbers:
                old = con.execute(
                    "SELECT data FROM registry WHERE reg_number=?", (number,)
                ).fetchone()
                # Не записывать результат по старой ссылке после параллельного импорта.
                if old and canonical_links(
                    RegistryRecord.model_validate_json(old[0]).cost_url
                ) == canonical_links(url):
                    con.execute(
                        "UPDATE registry SET price=? WHERE reg_number=?",
                        (result.model_dump_json(), number),
                    )

    def restore_prices(self, results: dict[int, PriceResult]) -> None:
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(
                "UPDATE registry SET price=? WHERE reg_number=?",
                [(value.model_dump_json(), number) for number, value in results.items()],
            )
