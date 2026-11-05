"""Data-source adapters. Each source is independent and swappable."""

from data.adapters.base import SourceAdapter, pair_code_of
from data.adapters.frankfurter import FRANKFURTER_BASE_URL, FrankfurterAdapter
from data.adapters.imf import IMF_BASE_URL, IMF_INDICATORS, ImfAdapter
from data.adapters.policy_rates import (
    ECB_POLICY_SERIES,
    EcbPolicyRateAdapter,
    FRED_POLICY_SERIES,
    FredAdapter,
    UNIMPLEMENTED_CENTRAL_BANKS,
)
from data.adapters.us_treasury import TREASURY_SERIES_CATALOG, US_TREASURY_BASE_URL, UsTreasuryAdapter
from data.adapters.world_bank import WORLD_BANK_BASE_URL, WORLD_BANK_INDICATORS, WorldBankAdapter

__all__ = [
    "SourceAdapter",
    "pair_code_of",
    "WorldBankAdapter",
    "WORLD_BANK_INDICATORS",
    "ImfAdapter",
    "IMF_INDICATORS",
    "FrankfurterAdapter",
    "EcbPolicyRateAdapter",
    "ECB_POLICY_SERIES",
    "FredAdapter",
    "FRED_POLICY_SERIES",
    "UsTreasuryAdapter",
    "TREASURY_SERIES_CATALOG",
    "UNIMPLEMENTED_CENTRAL_BANKS",
    "WORLD_BANK_BASE_URL",
    "FRANKFURTER_BASE_URL",
    "IMF_BASE_URL",
    "US_TREASURY_BASE_URL",
]
