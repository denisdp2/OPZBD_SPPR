"""Общие модели данных для API, хранилища, импорта и расчётов."""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ItemKind = Literal["tool", "org"]
"""Тип элемента защиты: tool — средство защиты (СЗИ/ПО), org — организационная мера."""

OptimizeMode = Literal["min_cost", "max_coverage", "compromise"]
"""Постановка задачи оптимизации.

min_cost      — взвешенное покрытие (Weighted Set Cover): закрыть обязательные
                требования с минимальной стоимостью;
max_coverage  — максимальное покрытие: как можно больше требований в бюджете
                (обязательные при этом должны быть закрыты).
compromise    — баланс стоимости, покрытия и срока внедрения на Парето-фронте.
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
    covers: List[str] = Field(default_factory=list)

    # Поля, значимые для средств защиты (kind == "tool")
    vendor: str = ""
    fstec_certified: bool = False
    fstec_cert_no: Optional[str] = None
    fstec_cert_valid_until: Optional[date] = None
    in_ru_software_registry: bool = False
    catalog_price: Optional[float] = Field(None, ge=0, allow_inf_nan=False)

    # Время внедрения в днях.
    implement_days: Optional[float] = Field(None, ge=0)


class Profile(_Model):
    """Профиль обязательности: какие требования обязательны в данном случае.

    Пример: «Значимый объект КИИ, 3 категория». Обязательность зависит от
    случая, а не от требования, поэтому хранится отдельно.
    """

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    mandatory: List[str] = Field(default_factory=list)


class DataBundle(_Model):
    """Полный набор справочников. Формат импорта/экспорта базы целиком."""

    requirements: List[Requirement] = Field(default_factory=list)
    items: List[Item] = Field(default_factory=list)
    profiles: List[Profile] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Сценарий пользователя (вводится в UI, может сохраняться в файл)
# --------------------------------------------------------------------------- #


class Candidate(_Model):
    """Выбранный пользователем элемент и введённая им стоимость."""

    item_id: str
    capex: float = Field(0, ge=0, description="Стоимость внедрения, руб.")
    opex_month: float = Field(0, ge=0, description="Стоимость эксплуатации в месяц, руб.")
    implement_days: float = Field(0, ge=0, description="Время внедрения в днях")


class Scenario(_Model):
    """Что выбрал пользователь в модуле принятия решений."""

    profile_id: Optional[str] = Field(None, description="Профиль обязательности")
    mandatory: Optional[List[str]] = Field(
        None, description="Явный список обязательных; если задан, профиль игнорируется"
    )
    period_months: float = Field(12, ge=0, description="Период, мес. (1 знак после запятой)")
    requirements: List[str] = Field(..., description="Требования, которые рассматриваем")
    candidates: List[Candidate] = Field(default_factory=list)

    @field_validator("period_months")
    @classmethod
    def _round_period(cls, v: float) -> float:
        return round(v, 1)


# --------------------------------------------------------------------------- #
#  Внутренняя постановка задачи — то, что получают оценка и оптимизация
# --------------------------------------------------------------------------- #


class Problem(_Model):
    """Данные для расчёта, собранные из сценария и справочников."""

    requirements: List[str]
    mandatory: List[str]
    items: List[Item]
    costs: Dict[str, float] = Field(description="item_id -> полная стоимость за период")
    period_months: float
    implementation_days: Dict[str, float] = Field(
        default_factory=dict, description="item_id -> пользовательское время внедрения, дни"
    )


# --------------------------------------------------------------------------- #
#  Результаты
# --------------------------------------------------------------------------- #


class EvaluationResult(_Model):
    """Результат кнопки «Оценить»."""

    all_mandatory_covered: bool
    uncovered_mandatory: List[str]
    covered: List[str]
    uncovered: List[str]
    covered_optional: int
    total_optional: int
    total_cost: float
    total_implementation_days: float = Field(
        0,
        ge=0,
        description="Сумма сроков внедрения выбранных позиций, дни",
    )
    covered_by: Dict[str, List[str]] = Field(
        default_factory=dict, description="требование -> какие элементы его закрывают"
    )


class Solution(_Model):
    """Один найденный набор элементов."""

    algorithm: str
    selected: List[str]
    cost: float
    covered_count: int
    feasible: bool = Field(description="Все обязательные требования закрыты")
    elapsed_ms: Optional[float] = None
    total_implementation_days: float = Field(
        0,
        ge=0,
        description="Сумма сроков внедрения выбранных позиций, дни",
    )


class OptimizeRequest(_Model):
    scenario: Scenario
    algorithm: str
    mode: OptimizeMode = "min_cost"
    budget: Optional[float] = Field(None, ge=0, description="Обязателен для mode=max_coverage")


class OptimizerInfo(_Model):
    name: str
    title: str
    exact: bool = Field(description="True — точный алгоритм, False — приближённый")
    description: str = ""
    supports_pareto: bool = False
    supported_modes: List[OptimizeMode] = Field(
        default_factory=lambda: ["min_cost", "max_coverage"]
    )


class ImportReport(_Model):
    importer: str
    imported: int
    errors: List[str] = Field(default_factory=list)
