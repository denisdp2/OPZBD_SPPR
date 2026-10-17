import pytest
from pydantic import ValidationError

from app.core.models import Candidate, Item, Scenario


def test_period_rounded_to_one_decimal():
    s = Scenario(requirements=[], period_months=12.46)
    assert s.period_months == 12.5


def test_negative_cost_rejected():
    with pytest.raises(ValidationError):
        Candidate(item_id="x", capex=-1)


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        Item(id="x", kind="hardware", name="x")


def test_extra_fields_rejected():
    """Опечатка в имени поля должна давать ошибку, а не молча теряться."""
    with pytest.raises(ValidationError):
        Item(id="x", kind="tool", name="x", cover=["A"])
