"""Хранилище справочников в SQLite."""

import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.interfaces import NotFoundError, Repository
from app.core.models import DataBundle, Item, ItemKind, Profile, Requirement


class SQLiteRepository(Repository):
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as con, con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS catalog "
                "(kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind, id))"
            )

    def _list(self, kind, model):
        with closing(sqlite3.connect(self.path)) as con:
            return [
                model.model_validate_json(row[0])
                for row in con.execute("SELECT data FROM catalog WHERE kind=? ORDER BY id", (kind,))
            ]

    def _get(self, kind, key, model):
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT data FROM catalog WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
        if row is None:
            raise NotFoundError(key)
        return model.model_validate_json(row[0])

    def _put(self, kind, value):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "INSERT OR REPLACE INTO catalog VALUES (?, ?, ?)",
                (kind, value.id, value.model_dump_json()),
            )

    def _delete(self, kind, key):
        with closing(sqlite3.connect(self.path)) as con, con:
            if not con.execute("DELETE FROM catalog WHERE kind=? AND id=?", (kind, key)).rowcount:
                raise NotFoundError(key)

    def list_requirements(self):
        return self._list("requirements", Requirement)

    def get_requirement(self, req_id):
        return self._get("requirements", req_id, Requirement)

    def upsert_requirement(self, req):
        self._put("requirements", req)

    def delete_requirement(self, req_id):
        self._delete("requirements", req_id)

    def list_items(self, kind: ItemKind | None = None):
        items = self._list("items", Item)
        return items if kind is None else [item for item in items if item.kind == kind]

    def get_item(self, item_id):
        return self._get("items", item_id, Item)

    def upsert_item(self, item):
        with closing(sqlite3.connect(self.path)) as con, con:
            self._write_item(con, item)

    @staticmethod
    def _write_item(con, item: Item) -> None:
        con.execute(
            "INSERT INTO catalog VALUES ('items', ?, ?) "
            "ON CONFLICT(kind, id) DO UPDATE SET data = CASE WHEN ? THEN excluded.data "
            "ELSE json_set(excluded.data, '$.catalog_price', "
            "json_extract(catalog.data, '$.catalog_price')) END",
            (item.id, item.model_dump_json(), "catalog_price" in item.model_fields_set),
        )

    def set_item_price(self, item_id: str, value: float | None) -> None:
        with closing(sqlite3.connect(self.path)) as con, con:
            updated = con.execute(
                "UPDATE catalog SET data=json_set(data, '$.catalog_price', ?) "
                "WHERE kind='items' AND id=?",
                (value, item_id),
            )
            if not updated.rowcount:
                raise NotFoundError(item_id)

    def delete_item(self, item_id):
        self._delete("items", item_id)

    def replace_item_coverage(
        self, item_id: str, expected: list[str], covers: list[str]
    ) -> Item | None:
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT data FROM catalog WHERE kind='items' AND id=?", (item_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(item_id)
            item = Item.model_validate_json(row[0])
            if item.covers != expected and item.covers != covers:
                return None
            known = {
                key for (key,) in con.execute("SELECT id FROM catalog WHERE kind='requirements'")
            }
            unknown = set(covers).difference(item.covers, known)
            if unknown:
                raise ValueError(f"Неизвестные требования: {', '.join(sorted(unknown))}")
            updated = item.model_copy(update={"covers": covers})
            con.execute(
                "UPDATE catalog SET data=? WHERE kind='items' AND id=?",
                (updated.model_dump_json(), item_id),
            )
            return updated

    def list_profiles(self):
        return self._list("profiles", Profile)

    def get_profile(self, profile_id):
        return self._get("profiles", profile_id, Profile)

    def upsert_profile(self, profile):
        self._put("profiles", profile)

    def delete_profile(self, profile_id):
        self._delete("profiles", profile_id)

    def import_bundle(self, bundle: DataBundle):
        count = 0
        with closing(sqlite3.connect(self.path)) as con, con:
            for kind in ("requirements", "items", "profiles"):
                for value in getattr(bundle, kind):
                    if kind == "items":
                        self._write_item(con, value)
                    else:
                        con.execute(
                            "INSERT OR REPLACE INTO catalog VALUES (?, ?, ?)",
                            (kind, value.id, value.model_dump_json()),
                        )
                    count += 1
        return count

    def review_coverage(self, links, kind: ItemKind, *, apply: bool, has_errors: bool):
        """Проверить связи и при подтверждении добавить их в одной транзакции."""
        added = existing = 0
        errors = []
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
            requirements = {
                key for (key,) in con.execute("SELECT id FROM catalog WHERE kind='requirements'")
            }
            pending = {}
            items = {}
            for number, item_id, requirement in links:
                if item_id not in items:
                    row = con.execute(
                        "SELECT data FROM catalog WHERE kind='items' AND id=?", (item_id,)
                    ).fetchone()
                    items[item_id] = Item.model_validate_json(row[0]) if row else None
                item = items[item_id]
                if item is None or item.kind != kind:
                    errors.append(f"Строка {number}: позиция «{item_id}» отсутствует в разделе")
                    continue
                if requirement not in requirements:
                    errors.append(f"Строка {number}: неизвестное требование «{requirement}»")
                    continue
                covers = pending.setdefault(item_id, dict.fromkeys(item.covers))
                if requirement in covers:
                    existing += 1
                else:
                    covers[requirement] = None
                    added += 1
            if apply and not (has_errors or errors):
                for item_id, covers in pending.items():
                    item = items[item_id]
                    if list(covers) == item.covers:
                        continue
                    updated = item.model_copy(update={"covers": list(covers)})
                    con.execute(
                        "UPDATE catalog SET data=? WHERE kind='items' AND id=?",
                        (updated.model_dump_json(), item_id),
                    )
        return added, existing, errors

    def export_bundle(self):
        return DataBundle(
            requirements=self.list_requirements(),
            items=self.list_items(),
            profiles=self.list_profiles(),
        )

    def uncovered_requirements(self):
        covered = {key for item in self.list_items() for key in item.covers}
        return [req for req in self.list_requirements() if req.id not in covered]
