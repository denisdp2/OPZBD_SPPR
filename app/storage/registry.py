"""Хранилище метаданных и цен Реестра российского ПО."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.core.models import Item
from app.importers.prices import PriceResult
from app.importers.registry import RegistryRecord
from app.importers.urls import canonical_links, source_url
from app.storage.connection import connect

_REGISTRY_PRICE = """COALESCE(manual_price, CASE
    WHEN json_extract(price, '$.status') IN ('ok', 'free')
    THEN json_extract(price, '$.value') END)"""


class RegistryStore:
    def __init__(self, path: Path):
        self.path = path
        with closing(connect(path)) as con, con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS registry "
                "(reg_number INTEGER PRIMARY KEY, data TEXT NOT NULL, "
                "price TEXT, manual_price REAL)"
            )

            columns = {row[1] for row in con.execute("PRAGMA table_info(registry)")}
            if "manual_price" not in columns:
                con.execute("ALTER TABLE registry ADD COLUMN manual_price REAL")
            con.execute(
                "CREATE TABLE IF NOT EXISTS registry_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def set_manual_price(self, number: int, value: float | None) -> bool:
        with closing(connect(self.path)) as con, con:
            cursor = con.execute(
                "UPDATE registry SET manual_price=? WHERE reg_number=?", (value, number)
            )
            return cursor.rowcount > 0

    def delete_record(self, number: int) -> None:
        with closing(connect(self.path)) as con, con:
            con.execute("DELETE FROM registry WHERE reg_number=?", (number,))

    def catalog_prices(self) -> dict[str, float | None]:
        with closing(connect(self.path)) as con:
            return dict(
                con.execute(f"SELECT 'ru-software-' || reg_number, {_REGISTRY_PRICE} FROM registry")
            )

    def upsert(
        self,
        records: list[RegistryRecord],
        *,
        imported: bool = False,
        source_date: str | None = None,
    ) -> None:
        with closing(connect(self.path)) as con, con:
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
            if imported and records:
                con.executemany(
                    "INSERT OR REPLACE INTO registry_metadata VALUES (?, ?)",
                    (
                        ("last_import_at", datetime.now(timezone.utc).isoformat()),
                        ("source_date", source_date or ""),
                    ),
                )

    def import_status(self) -> dict[str, str | None]:
        with closing(connect(self.path)) as con:
            values = dict(con.execute("SELECT key, value FROM registry_metadata"))
        return {
            "last_import_at": values.get("last_import_at"),
            "source_date": values.get("source_date") or None,
        }

    def coverage_records(self) -> list[RegistryRecord]:
        with closing(connect(self.path)) as con:
            return [
                RegistryRecord.model_validate_json(data)
                for (data,) in con.execute("SELECT data FROM registry")
            ]

    def get_record(self, number: int) -> RegistryRecord | None:
        with closing(connect(self.path)) as con:
            row = con.execute("SELECT data FROM registry WHERE reg_number=?", (number,)).fetchone()
        return RegistryRecord.model_validate_json(row[0]) if row else None

    def list_records(self) -> list[dict]:
        with closing(connect(self.path)) as con:
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

    def tools_page(self, q, state, sort, descending, offset, limit) -> dict:
        sort_columns = {
            "reg_number": "reg_number",
            "id": "casefold(id)",
            "name": "casefold(json_extract(item, '$.name'))",
            "covers": "casefold(COALESCE(json_extract(item, '$.covers'), '[]'))",
            "owner": "casefold(COALESCE(json_extract(item, '$.vendor'), ''))",
            "status": "excluded",
            "value": "value",
            "source": "casefold(COALESCE(url, ''))",
        }
        order = sort_columns[sort]
        direction = "DESC" if descending else "ASC"
        base = f"""
            WITH tools AS (
                SELECT c.id, c.data AS item, r.data AS record, r.price, r.manual_price,
                    r.reg_number,
                    COALESCE(json_extract(r.data, '$.exclusion_date'), '') AS excluded,
                    CASE WHEN r.reg_number IS NULL THEN json_extract(c.data, '$.catalog_price')
                        ELSE {_REGISTRY_PRICE} END AS value,
                    COALESCE(NULLIF(json_extract(r.price, '$.source_url'), ''),
                        json_extract(r.data, '$.cost_url')) AS url
                FROM catalog AS c
                LEFT JOIN registry AS r ON r.reg_number = CAST(substr(c.id, 13) AS INTEGER)
                    AND c.id = 'ru-software-' || r.reg_number
                WHERE c.kind = 'items' AND json_extract(c.data, '$.kind') = 'tool'
            )
        """
        where = """
            WHERE (excluded != '') = ? AND
              (? = '' OR instr(casefold(id || ' ' || json_extract(item, '$.name') || ' ' ||
                COALESCE(json_extract(item, '$.vendor'), '')), ?) > 0)
        """
        query = q.strip().casefold()
        params = (state == "excluded", query, query)
        with closing(connect(self.path)) as con, con:
            con.create_function("casefold", 1, str.casefold, deterministic=True)
            con.execute("BEGIN")
            total = con.execute(base + "SELECT COUNT(*) FROM tools " + where, params).fetchone()[0]
            rows = con.execute(
                base
                + "SELECT item, record, price, manual_price, url FROM tools "
                + where
                + f"ORDER BY ({order}) IS NULL, {order} {direction}, id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        items = []
        for item, record, price, manual_price, url in rows:
            result = (
                PriceResult(status="ok", value=manual_price)
                if manual_price is not None
                else PriceResult.model_validate_json(price)
                if price
                else None
            )
            items.append(
                {
                    "item": Item.model_validate_json(item),
                    "record": RegistryRecord.model_validate_json(record) if record else None,
                    "price": result,
                    "manual_price": manual_price,
                    "source_url": source_url(url) if url else None,
                }
            )
        return {"total": total, "items": items}

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
        with closing(connect(self.path)) as con, con:
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
        with closing(connect(self.path)) as con, con:
            con.executemany(
                "UPDATE registry SET price=? WHERE reg_number=?",
                [(value.model_dump_json(), number) for number, value in results.items()],
            )
