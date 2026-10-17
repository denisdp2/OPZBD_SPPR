"""Абстрактные интерфейсы модулей.

Каждый модуль реализует свой интерфейс, а остальные пользуются только им:

* Repository — хранилище (требования, средства, оргмеры, профили);
* Importer   — загрузка данных из файлов (JSON, Excel, выгрузки реестров);
* Optimizer  — алгоритм подбора оптимального набора.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Literal

from app.core.models import (
    DataBundle,
    Item,
    ItemKind,
    OptimizeMode,
    Problem,
    Profile,
    Requirement,
    Solution,
)


class NotFoundError(KeyError):
    """Запрошенная запись не найдена в хранилище."""


# --------------------------------------------------------------------------- #
#  Хранилище — app/storage
# --------------------------------------------------------------------------- #


class Repository(ABC):
    """Хранилище справочников."""

    # ---- требования ----
    @abstractmethod
    def list_requirements(self) -> list[Requirement]: ...

    @abstractmethod
    def get_requirement(self, req_id: str) -> Requirement:
        """Бросает NotFoundError, если записи нет."""

    @abstractmethod
    def upsert_requirement(self, req: Requirement) -> None:
        """Добавить или заменить запись с тем же id."""

    @abstractmethod
    def delete_requirement(self, req_id: str) -> None:
        """Бросает NotFoundError, если записи нет."""

    # ---- средства и меры ----
    @abstractmethod
    def list_items(self, kind: ItemKind | None = None) -> list[Item]:
        """Все элементы или только указанного типа."""

    @abstractmethod
    def get_item(self, item_id: str) -> Item: ...

    @abstractmethod
    def upsert_item(self, item: Item) -> None: ...

    @abstractmethod
    def delete_item(self, item_id: str) -> None: ...

    # ---- профили обязательности ----
    @abstractmethod
    def list_profiles(self) -> list[Profile]: ...

    @abstractmethod
    def get_profile(self, profile_id: str) -> Profile: ...

    @abstractmethod
    def upsert_profile(self, profile: Profile) -> None: ...

    @abstractmethod
    def delete_profile(self, profile_id: str) -> None: ...

    # ---- база целиком ----
    @abstractmethod
    def import_bundle(self, bundle: DataBundle) -> int:
        """Записать набор данных. Возвращает число записанных записей."""

    @abstractmethod
    def export_bundle(self) -> DataBundle:
        """Выгрузить всю базу."""

    @abstractmethod
    def uncovered_requirements(self) -> list[Requirement]:
        """Требования, которые не закрывает ни одно средство или мера."""


# --------------------------------------------------------------------------- #
#  Импорт — app/importers
# --------------------------------------------------------------------------- #


class Importer(ABC):
    """Загрузчик данных из файла.

    Импортёр не пишет в хранилище сам: он разбирает файл и возвращает
    DataBundle и список ошибок, а запись выполняет API.
    """

    name: ClassVar[str]
    """Короткое имя для URL: /api/admin/import/{name}"""

    title: ClassVar[str]
    """Название для интерфейса администратора."""

    target: ClassVar[Literal["requirements", "items", "profiles", "bundle"]]

    extensions: ClassVar[tuple[str, ...]] = ()
    """Допустимые расширения файлов, например ('.xlsx',)."""

    @abstractmethod
    def parse(self, path: Path) -> tuple[DataBundle, list[str]]:
        """Разобрать файл: (корректные записи, человекочитаемые ошибки)."""


# --------------------------------------------------------------------------- #
#  Оптимизация — app/optimization
# --------------------------------------------------------------------------- #


class Optimizer(ABC):
    """Алгоритм подбора набора средств и мер. Получает только Problem."""

    name: ClassVar[str]
    """Короткое уникальное имя алгоритма."""

    title: ClassVar[str]
    exact: ClassVar[bool]
    """True — точный алгоритм, False — приближённый."""

    description: ClassVar[str] = ""
    supports_pareto: ClassVar[bool] = False

    @abstractmethod
    def solve(
        self, problem: Problem, mode: OptimizeMode = "min_cost", budget: float | None = None
    ) -> Solution:
        """Найти лучший набор.

        min_cost:     все обязательные закрыты, стоимость минимальна;
        max_coverage: стоимость <= budget, обязательные закрыты,
                      число закрытых требований максимально.
        Если допустимого решения нет — Solution с feasible=False.
        """

    def pareto(self, problem: Problem) -> list[Solution]:
        """Парето-фронт «стоимость / число закрытых требований».

        Необязательный метод: переопределяется, если supports_pareto = True.
        """
        raise NotImplementedError
