"""SQLite connection with JSON helpers for the Windows Python 3.8 build."""

import json
import sqlite3
from contextlib import closing
from functools import lru_cache


@lru_cache(maxsize=1)
def _has_json() -> bool:
    with closing(sqlite3.connect(":memory:")) as con:
        try:
            con.execute("SELECT json_extract('{}', '$.value')")
        except sqlite3.OperationalError:
            return False
    return True


def _json_extract(document, path):
    if document is None:
        return None
    value = json.loads(document).get(path[2:])
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _json_set(document, path, value):
    data = json.loads(document)
    data[path[2:]] = value
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def connect(path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    if not _has_json():
        # Catalog queries use two JSON operations over top-level object fields.
        con.create_function("json_extract", 2, _json_extract, deterministic=True)
        con.create_function("json_set", 3, _json_set, deterministic=True)
    return con
