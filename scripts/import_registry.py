"""Импорт реестра без браузера: python -m scripts.import_registry путь.xlsx/путь.db."""

import argparse
from pathlib import Path

from app import paths
from app.importers.service import RegistryService
from app.storage.registry import RegistryStore
from app.storage.sqlite import SQLiteRepository


def main():
    parser = argparse.ArgumentParser(description="Перенос выгрузки или базы реестра в СППР")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    path = paths.data_dir() / "catalog.sqlite3"
    service = RegistryService(SQLiteRepository(path), RegistryStore(path))
    report = service.import_file(args.source)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
