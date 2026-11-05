"""HTTP helpers for data-source adapters.

A single hardened client: sane timeouts, an identifiable User-Agent,
retries with backoff on transient failures. Adapters inject their own
``httpx.Client`` in tests (``httpx.MockTransport``) so tests never touch
the network.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(45.0, connect=15.0)
MAX_RETRIES = 3
_RETRYABLE = {429, 500, 502, 503, 504}


class HttpFetchError(RuntimeError):
    """Raised when a source cannot be fetched after retries. Never swallowed."""


def make_client(
    base_url: str | None = None,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    **client_kwargs: Any,
) -> httpx.Client:
    """Build an HTTP client with an honest, identifiable User-Agent."""
    headers = {
        "User-Agent": "infinite-money-glitch-detector/0.2.0 (economic research)",
        "Accept": "application/json, text/csv;q=0.9, */*;q=0.8",
    }
    if base_url is not None:
        client_kwargs["base_url"] = base_url
    return httpx.Client(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
        **client_kwargs,
    )


def _get_with_retries(client: httpx.Client, url: str, params: dict[str, Any] | None) -> httpx.Response:
    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as exc:  # network-level error
            last_error = str(exc)
        else:
            if response.status_code == 200:
                return response
            if response.status_code not in _RETRYABLE:
                raise HttpFetchError(
                    f"GET {url} failed with HTTP {response.status_code} (not retryable). "
                    "Check the endpoint and any required credentials."
                )
            last_error = f"HTTP {response.status_code}"
        if attempt < MAX_RETRIES:
            time.sleep(1.5 ** attempt)
    raise HttpFetchError(f"GET {url} failed after {MAX_RETRIES} attempts: {last_error}")


def get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    """GET and parse JSON, with retries on transient failures."""
    return _get_with_retries(client, url, params).json()


def get_text(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> str:
    """GET and return the response body as text (e.g. CSV endpoints)."""
    return _get_with_retries(client, url, params).text
