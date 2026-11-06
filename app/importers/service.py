"""Оркестрация импорта и фонового сбора цен, независимо от HTTP и интерфейса."""

import asyncio
from collections import defaultdict
from itertools import islice
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

import httpx

from app.core.interfaces import Repository
from app.core.models import DataBundle, ImportReport
from app.importers.legacy_registry import LegacyRegistryImporter
from app.importers.prices import PARSER_VERSION, PriceResult, collect_price, tls_context
from app.importers.registry import RegistryImporter
from app.importers.urls import canonical_links
from app.storage.registry import RegistryStore


class RegistryService:
    def __init__(self, repo: Repository, store: RegistryStore):
        self.repo, self.store = repo, store
        self.lock = Lock()
        self.job = {"status": "idle", "total": 0, "done": 0, "errors": 0}

    def import_file(self, path: Path) -> ImportReport:
        if path.suffix.lower() in LegacyRegistryImporter.extensions:
            records, results, errors = LegacyRegistryImporter().read_source(path)
            importer = LegacyRegistryImporter.name
        else:
            records, errors = RegistryImporter().parse_records(path)
            results = {}
            importer = RegistryImporter.name
        items = []
        existing = {item.id: item for item in self.repo.list_items()}
        for record in records:
            fresh = record.to_item()
            previous = existing.get(fresh.id)
            if previous is not None:
                # Обновляем только поля, принадлежащие источнику.
                fresh = previous.model_copy(
                    update={
                        "name": fresh.name,
                        "vendor": fresh.vendor,
                        "in_ru_software_registry": fresh.in_ru_software_registry,
                    }
                )
            items.append(fresh)
        self.repo.import_bundle(DataBundle(items=items))
        self.store.upsert(records)
        if results:
            self.store.restore_prices(results)
        return ImportReport(importer=importer, imported=len(items), errors=errors)

    def start(self, retry: bool, limit: int, refresh: bool = False) -> dict:
        with self.lock:
            if self.job["status"] == "running":
                raise ValueError("Сбор стоимости уже выполняется")
            groups = defaultdict(list)
            entries = self.store.list_records()
            reusable = {}
            for entry in entries:
                price = entry["price"]
                if (
                    price
                    and price.get("parser_version", 1) >= PARSER_VERSION
                    and not refresh
                    and (not retry or price["status"] in {"ok", "free", "scan"})
                ):
                    url = canonical_links(entry["record"]["cost_url"])
                    previous = reusable.get(url)
                    if previous is None or price["status"] in {"ok", "free"}:
                        reusable[url] = price
            cached = defaultdict(list)
            for entry in entries:
                record, price = entry["record"], entry["price"]
                if record["exclusion_date"] or not record["cost_url"]:
                    continue
                if (
                    price
                    and not refresh
                    and price.get("parser_version", 1) >= PARSER_VERSION
                    and (not retry or price["status"] not in {"error", "js", "no_price", "other"})
                ):
                    continue
                url = canonical_links(record["cost_url"])
                if url in reusable:
                    cached[url].append(record["reg_number"])
                    continue
                if refresh or url in groups or len(groups) < limit:
                    groups[url].append(record["reg_number"])
            for url, numbers in cached.items():
                self.store.save_price(numbers, PriceResult.model_validate(reusable[url]), url)
            self.pending = dict(groups)
            self.batch_size = limit
            self.job = {"status": "running", "total": len(groups), "done": 0, "errors": 0}
            return dict(self.job)

    def status(self) -> dict:
        with self.lock:
            return dict(self.job)

    async def run(self) -> None:
        pending = iter(self.pending.items())
        queue = asyncio.Queue()
        hosts = defaultdict(lambda: asyncio.Semaphore(2))

        async def worker(client):
            while not queue.empty():
                url, numbers = queue.get_nowait()
                # Даже некорректная ссылка должна давать ошибку одной записи, не всей задачи.
                try:
                    host = urlsplit(url).hostname or ""
                except ValueError:
                    host = ""
                async with hosts[host]:
                    result = await collect_price(client, url)
                await asyncio.to_thread(self.store.save_price, numbers, result, url)
                with self.lock:
                    self.job["done"] += 1
                    self.job["errors"] += result.status == "error"

        try:
            async with httpx.AsyncClient(
                timeout=18,
                verify=tls_context(),
                trust_env=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; SZI-SPPR/0.1)",
                    "Accept-Language": "ru,en;q=0.8",
                },
            ) as client:
                while batch := list(islice(pending, self.batch_size)):
                    for pair in batch:
                        queue.put_nowait(pair)
                    workers = [
                        asyncio.create_task(worker(client)) for _ in range(min(8, len(batch)))
                    ]
                    try:
                        await asyncio.gather(*workers)
                    finally:
                        for task in workers:
                            task.cancel()
                        await asyncio.gather(*workers, return_exceptions=True)
            with self.lock:
                self.job["status"] = "completed"
        except Exception as exc:
            with self.lock:
                self.job.update(status="failed", message=str(exc)[:200])
