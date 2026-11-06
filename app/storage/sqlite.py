"""Портативное хранилище справочников: общие модели сериализуются без потери полей."""

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
        self._put("items", item)

    def delete_item(self, item_id):
        self._delete("items", item_id)

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
                    con.execute(
                        "INSERT OR REPLACE INTO catalog VALUES (?, ?, ?)",
                        (kind, value.id, value.model_dump_json()),
                    )
                    count += 1
        return count

    def export_bundle(self):
        return DataBundle(
            requirements=self.list_requirements(),
            items=self.list_items(),
            profiles=self.list_profiles(),
        )

    def uncovered_requirements(self):
        covered = {key for item in self.list_items() for key in item.covers}
        return [req for req in self.list_requirements() if req.id not in covered]
