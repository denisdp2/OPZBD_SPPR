"""Общие модели данных проекта.

Это единственный источник правды о формате данных. Все модули (хранилище,
импорт, оценка, оптимизация, API, фронтенд) обмениваются только этими
моделями. Менять их можно только через Pull Request с ревью архитектора.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ItemKind = Literal["tool", "org"]
"""Тип элемента защиты: tool — средство защиты (СЗИ/ПО), org — организационная мера."""

OptimizeMode = Literal["min_cost", "max_coverage"]
"""Постановка задачи оптимизации.

min_cost      — закрыть все обязательные требования с минимальной стоимостью;
max_coverage  — закрыть как можно больше требований в рамках бюджета
                (обязательные при этом должны быть закрыты).
"""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
#  Справочники (хранятся в БД, редактируются через админку)
# --------------------------------------------------------------------------- #


class Requirement(_Model):
    """Требование (мера из нормативного документа), например «ИАФ.1»."""

    id: str = Field(..., min_length=1, description="Уникальный код, например 'ИАФ.1'")
    group: str = Field("", description="Группа мер, например 'ИАФ'")
    title: str = Field(..., min_length=1)
    source: str = Field("", description="Нормативный документ-источник")
    description: str = ""


class Item(_Model):
    """Средство защиты или организационная мера. Единый пул для выбора.

    Поле ``covers`` — список id требований, которые закрывает элемент.
    Сопоставление задаётся вручную через интерфейс администратора.
    """

    id: str = Field(..., min_length=1)
    kind: ItemKind
    name: str = Field(..., min_length=1)
    description: str = ""
    covers: list[str] = Field(default_factory=list)

    # Поля, значимые для средств защиты (kind == "tool")
    vendor: str = ""
    fstec_certified: bool = False
    fstec_cert_no: str | None = None
    fstec_cert_valid_until: date | None = None
    in_ru_software_registry: bool = False

    # Для бонусной части: время внедрения
    implement_days: float | None = Field(None, ge=0)


class Profile(_Model):
    """Профиль обязательности: какие требования обязательны в данном случае.

    Пример: «Значимый объект КИИ, 3 категория». Обязательность зависит от
    случая, а не от требования, поэтому хранится отдельно.
    """

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    mandatory: list[str] = Field(default_factory=list)


class DataBundle(_Model):
    """Полный набор справочников. Формат импорта/экспорта базы целиком."""

    requirements: list[Requirement] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    profiles: list[Profile] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Сценарий пользователя (вводится в UI, может сохраняться в файл)
# --------------------------------------------------------------------------- #


class Candidate(_Model):
    """Выбранный пользователем элемент и введённая им стоимость."""

    item_id: str
    capex: float = Field(0, ge=0, description="Стоимость внедрения, руб.")
    opex_month: float = Field(0, ge=0, description="Стоимость эксплуатации в месяц, руб.")


class Scenario(_Model):
    """Что выбрал пользователь в модуле принятия решений."""

    profile_id: str | None = Field(None, description="Профиль обязательности")
    mandatory: list[str] | None = Field(
        None, description="Явный список обязательных; если задан, профиль игнорируется"
    )
    period_months: float = Field(12, ge=0, description="Период, мес. (1 знак после запятой)")
    requirements: list[str] = Field(..., description="Требования, которые рассматриваем")
    candidates: list[Candidate] = Field(default_factory=list)

    @field_validator("period_months")
    @classmethod
    def _round_period(cls, v: float) -> float:
        return round(v, 1)


# --------------------------------------------------------------------------- #
#  Внутренняя постановка задачи — то, что получают оценка и оптимизация
# --------------------------------------------------------------------------- #


class Problem(_Model):
    """Полностью разрешённая задача, без ссылок на БД.

    Строится из Scenario + Repository функцией ``app.core.problem.build_problem``.
    Алгоритмы и оценка работают только с ней, поэтому их можно тестировать
    без базы данных и без интерфейса.
    """

    requirements: list[str]
    mandatory: list[str]
    items: list[Item]
    costs: dict[str, float] = Field(description="item_id -> полная стоимость за период")
    period_months: float


# --------------------------------------------------------------------------- #
#  Результаты
# --------------------------------------------------------------------------- #


class EvaluationResult(_Model):
    """Результат кнопки «Оценить»."""

    all_mandatory_covered: bool
    uncovered_mandatory: list[str]
    covered: list[str]
    uncovered: list[str]
    covered_optional: int
    total_optional: int
    total_cost: float
    covered_by: dict[str, list[str]] = Field(
        default_factory=dict, description="требование -> какие элементы его закрывают"
    )


class Solution(_Model):
    """Один найденный набор элементов."""

    algorithm: str
    selected: list[str]
    cost: float
    covered_count: int
    feasible: bool = Field(description="Все обязательные требования закрыты")
    elapsed_ms: float | None = None


class OptimizeRequest(_Model):
    scenario: Scenario
    algorithm: str
    mode: OptimizeMode = "min_cost"
    budget: float | None = Field(None, ge=0, description="Обязателен для mode=max_coverage")


class OptimizerInfo(_Model):
    name: str
    title: str
    exact: bool = Field(description="True — точный алгоритм, False — приближённый")
    description: str = ""
    supports_pareto: bool = False


class ImportReport(_Model):
    importer: str
    imported: int
    errors: list[str] = Field(default_factory=list)
