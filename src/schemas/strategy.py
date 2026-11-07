"""Shared schemas and vocabulary for every strategy type.

These contracts are intentionally separated from the numerical engine so
that a Python script, a backtester, an API endpoint and (later) the AI
assistant all enforce identical input validation. No calculation logic
belongs in this module.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from core.currency import (
    validate_currency_code,
)


class InterestConvention(str, Enum):
    """Interest compounding convention.

    Never implicit: callers must pass this explicitly where it matters.
    """

    SIMPLE = "simple"
    COMPOUND = "compound"


class CurrencyPair(BaseModel):
    """The two currencies of a cross-currency strategy."""

    borrowing_currency: str = Field(description="ISO 4217 style code of the borrowed currency (A)")
    investment_currency: str = Field(description="ISO 4217 style code of the investment currency (B)")

    @field_validator("borrowing_currency", "investment_currency")
    @classmethod
    def _valid_code(cls, value: str) -> str:
        return validate_currency_code(value)

    @model_validator(mode="after")
    def _currencies_must_differ(self) -> "CurrencyPair":
        if self.borrowing_currency == self.investment_currency:
            raise ValueError(
                f"borrowing_currency and investment_currency must differ, got {self.borrowing_currency!r} twice."
            )
        return self
