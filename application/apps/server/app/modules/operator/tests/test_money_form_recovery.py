"""Regression tests for incomplete MoneyForm draft recovery payloads."""

import pytest
from pydantic import ValidationError

from app.modules.operator.application.financial_forms import ExpenseCreateForm


@pytest.mark.parametrize("amount", [None, "0", "0.00", "-5", "12", "12.", "12.34"])
def test_expense_create_draft_accepts_incomplete_or_invalid_amount_strings(amount):
    form = ExpenseCreateForm.model_validate({"amount": amount})
    assert form.amount == amount


def test_expense_create_draft_rejects_oversized_or_non_string_amount():
    with pytest.raises(ValidationError):
        ExpenseCreateForm.model_validate({"amount": "1" * 33})
    with pytest.raises(ValidationError):
        ExpenseCreateForm.model_validate({"amount": 12.34})
