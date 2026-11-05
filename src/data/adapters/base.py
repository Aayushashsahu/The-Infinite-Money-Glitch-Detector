"""Source-adapter base layer and fetch result contracts.

Every economic source is wrapped in an independent adapter with the
same contract: given an injected HTTP client (real in production,
``httpx.MockTransport`` in tests), it returns normalized
:class:`FetchResult` objects plus the raw payloads they were derived
from. Adapters know nothing about the database, dashboards or AI.

Documented per-source facts (not assumptions) are carried in code
comments and in ``docs/phase2.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from data.http import make_client
from data.schemas import FetchResult


class SourceAdapter(ABC):
    """Common base for all data-source adapters."""

    source_id: str
    display_name: str

    def __init__(self, client: httpx.Client | None = None):
        # Tests inject a MockTransport-backed client; production gets a
        # real one. No adapter constructs I/O implicitly elsewhere.
        self._client = client if client is not None else make_client()

    @property
    def client(self) -> httpx.Client:
        return self._client

    @abstractmethod
    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch data from the source and return a normalized result."""

    # -- shared helper -----------------------------------------------------

    def _obs_kwargs(self, **values: Any) -> dict[str, Any]:
        """Common observation keyword arguments (source_id, timestamp)."""
        return values


def pair_code_of(base: str, quote: str) -> str:
    """Canonical pair code ``'{BASE}/{QUOTE}'`` (uniform quotation convention)."""
    return f"{base}/{quote}"
