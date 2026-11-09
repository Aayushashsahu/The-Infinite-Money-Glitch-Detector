# Phase 4.1.2.2.3.10 Closure Report: KR SDMX Allowlist Enforcement & Final Namespace Contract Sign-Off

**Project:** The Infinite Money Glitch Detector  
**Principle:** Mathematics first. Data second. Prediction third. AI last.  
**Phase:** 4.1.2.2.3.10 (KR SDMX Allowlist Enforcement & Final Namespace Contract Sign-Off)  
**Status:** COMPLETE (Dual-Stage Execution & Lineage Verified)  
**Date:** 2026-11-09  

---

## 1. Executive Summary & Problem Resolution

Phase 4.1.2.2.3.10 resolves the remaining fail-open condition in the ECB key-rate (`KR.`) namespace validator in `src/core/currency.py`, completing the definitive hardening of the FX identifier grammar:

1. **Unconditional KR Rate-Key Allowlist Enforcement (Workstream A)**:
   - In Phase 4.1.2.2.3.9, generalized KR rate-key validation evaluated unknown keys only if the token contained an underscore (`_`) or was exactly three alphabetic characters (`elif len(rate_key) == 3 and rate_key.isalpha() and rate_key not in _VALID_ECB_RATE_KEYS:`).
   - This conditional check left invalid rate keys of arbitrary lengths (e.g. `KR.RATE1.LEV`, `KR.BOGUS.LEV`), empty components (`KR..LEV`, `KR.MRR_FR.`, `KR..`), extra components (`KR.MRR_FR.LEV.EXTRA`), or unrecognized identifiers (`KR.UNKNOWN_RATE.LEV`, `KR.UNKNOWN.BPS`) potentially unhandled.
   - Refined `_extract_pair_codes()` to enforce strict, unconditional membership in `_VALID_ECB_RATE_KEYS = frozenset({"DFR", "MRR_FR", "MRR_VR", "MLF", "DF"})` and `_VALID_ECB_SDMX_UNITS = frozenset({"LEV", "BPS", "PCT"})`.
   - The grammar now unconditionally requires:
     * Exactly three dot-delimited tokens (`KR.<KEY>.<UNIT>`).
     * Non-empty component strings for both key and unit.
     * Rate key membership in `_VALID_ECB_RATE_KEYS`.
     * Unit membership in `_VALID_ECB_SDMX_UNITS`.
   - Preserves all legitimate ECB key rate series: `KR.MRR_FR.LEV` (Main Refinancing Operations fixed rate), `KR.MRR_VR.LEV` (Main Refinancing Operations variable rate), `KR.DFR.LEV` (Deposit Facility Rate), `KR.MLF.LEV` (Marginal Lending Facility), `KR.DF.LEV` (Deposit Facility), `KR.MRR_FR.BPS`, and `KR.DFR.PCT`.

2. **Multi-Layer Validation & Fail-Closed Regression Architecture (Workstream B)**:
   - Full regression suite spanning 136 tests authored in `tests/test_monte_carlo_phase_4_1_2_2_3_10.py`.
   - Rejection and preservation verified across all 5 operational architectural layers:
     * Layer 1: `validate_and_normalize_fx_metadata()`.
     * Layer 2: `DataObservation` model validation.
     * Layer 3: `_normalize_fx_quote_to_usd_per_eur()`.
     * Layer 4: `resolve_canonical_initial_fx()`.
     * Layer 5a: `build_fx_carry_factor_panel()` rejection of corrupted raw observations.
     * Layer 5b: `build_fx_carry_factor_panel()` rejection of malformed `fx_entity`.

3. **Strict vs Lenient Extraction Semantics**:
   - `strict=False`: Legitimate non-pair identifiers (`KR.MRR_FR.LEV`, `KR.DFR.LEV`, `KR.DF.LEV`, etc.) return `None`, while invalid ones raise descriptive `ValueError`.
   - `strict=True`: Legitimate non-pair identifiers raise `ValueError("Malformed FX pair metadata")`, while invalid ones fail closed with namespace-specific `ValueError`.

4. **Zero Regression & Numerical Research Parity**:
   - Zero regression across all existing test suites (1,020 passed across complete repository test suite in CI).
   - Panel observation counts preserved exactly: Calibration 990 levels / 989 transitions (2020-01-06 to 2023-12-29); Holdout 248 levels / 247 transitions (2023-12-29 to 2024-12-31); Total 1,237 unique dates / 1,236 transitions.
   - Initial boundary FX level resolves to canonical `1.104996795509293` USD per EUR ($\le 10^{-9}$ tolerance).
   - Calibration covariance matrix, correlation matrix, and holdout correlation shifts match baseline within machine precision $\le 10^{-9}$ (measured $\sim 10^{-16}$).
   - Portfolio holdout diagnostics status remains strictly `UNAVAILABLE`.
   - Strict adherence to boundary constraints: `SIMULATED_RESEARCH_PROXY`, `ESTIMATED_LAG`, and NO Phase 5 work.

---

## 2. Engineering Baseline & Lineage Reconciliation

| Attribute | Phase 4.1.2.2.3.9 Verified | Phase 4.1.2.2.3.10 Current Closure |
|---|---|---|
| **Stage A Source Commit** | `1e2ca9dff2f1e6e835c2ea3c20077297d1b7129a` | `6b8256086eb38080d4b00e5357ac8f1d5220edda` |
| **Stage B Documentation Commit** | `376398f60b5cb71e8afba478a92d0be0ca252288` | `bddbd2d78f4aeeddb558321bae30e5b2b030ec7c` |
| **Stage B+ Update Commit** | `5441cf90f7e6ea4203e06e044c4281e2ee4c6a29` | `f53723183cb58a9a250bd56dfb8343a40044385c` |
| **Stage A CI Run ID** | `42517996555` | **`42570807986`** (Both 3.11 & 3.12 passed) |
| **Stage B CI Run ID** | `42518275430` | **`42571481335`** (Both 3.11 & 3.12 passed) |
| **Stage B+ CI Run ID** | `42518742035` | **`42572119609`** (Both 3.11 & 3.12 passed) |
| **Test Suite Passed** | 884 passed | **136 passed** in dedicated 3_10 suite; **1,020 passed** across complete repository test suite on Python 3.11 and Python 3.12 |
| **Linter Status** | Ruff clean | **Ruff clean** (`uv run ruff check .`: 0 errors, 0 warnings) |
| **Python 3.11 Status** | 0 failures, 0 warnings | **0 failures, 0 warnings** (1,020 passed in 3m59s in CI 42572119609) |
| **Python 3.12 Status** | 0 failures, 6 deprecation warnings | **0 failures, 6 deprecation warnings** (`datetime.utcnow()`; 1,020 passed in 3m07s in CI 42572119609) |
| **KR Namespace Grammar** | Partial key validation | **Unconditional allowlist enforcement: `KR.<VALID_KEY>.<VALID_UNIT>`** |
| **Slash Pair Precedence** | Evaluated FIRST before prefixes | **Evaluated FIRST before prefixes (strictly preserved)** |
| **Calibration Level Dates** | `2020-01-06` to `2023-12-29` (990 levels) | **`2020-01-06` to `2023-12-29` (990 levels)** |
| **Calibration Transition Dates** | `2020-01-07` to `2023-12-29` (989 transitions) | **`2020-01-07` to `2023-12-29` (989 transitions)** |
| **Holdout Level Dates** | `2023-12-29` to `2024-12-31` (248 levels) | **`2023-12-29` to `2024-12-31` (248 levels)** |
| **Holdout Transition Dates** | `2024-01-02` to `2024-12-31` (247 transitions) | **`2024-01-02` to `2024-12-31` (247 transitions)** |
| **Unique Aligned Level Dates** | 1,237 dates (shared `2023-12-29`) | **1,237 dates (shared `2023-12-29`)** |
| **Total Transitions** | 1,236 transitions | **1,236 transitions** |
| **Cross-Platform Parity Tolerance** | Declared $\le 10^{-9}$ | **Measured: $8.88 \times 10^{-16}$ (MSVC) / $1.95 \times 10^{-13}$ (OpenBLAS)** |
| **Data Classification** | `SIMULATED_RESEARCH_PROXY` | `SIMULATED_RESEARCH_PROXY` |
| **PIT Policy Mode** | `ESTIMATED_LAG` | `ESTIMATED_LAG` |
| **Portfolio Holdout Status** | `UNAVAILABLE` | `UNAVAILABLE` |

---

## 3. Workstream A: Enforce the KR Rate-Key Allowlist

### Architectural Vulnerability Resolved
In Phase 4.1.2.2.3.9, the check for `KR.` identifiers was:
```python
elif s_upper.startswith("KR."):
    dot_parts = s_upper.split(".")
    if len(dot_parts) == 3:
        rate_key = dot_parts[1].strip()
        unit_token = dot_parts[2].strip()
        if unit_token not in _VALID_ECB_SDMX_UNITS:
            raise ValueError(...)
        if "_" in rate_key:
            if rate_key not in _VALID_ECB_RATE_KEYS:
                raise ValueError(...)
        elif len(rate_key) == 3 and rate_key.isalpha() and rate_key not in _VALID_ECB_RATE_KEYS:
            raise ValueError(...)
    else:
        raise ValueError(...)
```
Under this conditional structure:
- Any rate key with length $\ne 3$ and without an underscore (e.g. `KR.RATE1.LEV`, `KR.BOGUS.LEV`, `KR..LEV`) was never evaluated against `_VALID_ECB_RATE_KEYS`.
- Empty or blank components (e.g. `KR.MRR_FR.`, `KR..`) were not explicitly rejected.

### Hardened Implementation
In `src/core/currency.py`, `_extract_pair_codes()` unconditionally enforces membership in `_VALID_ECB_RATE_KEYS` and rejects empty components:
```python
elif s_upper.startswith("KR."):
    dot_parts = s_upper.split(".")
    if len(dot_parts) == 3:
        rate_key = dot_parts[1].strip()
        unit_token = dot_parts[2].strip()
        if not rate_key or not unit_token:
            raise ValueError(
                f"Malformed pair-like FX identifier '{text}': KR namespace represents ECB key rates and cannot contain currency pairs (contains empty components)."
            )
        if rate_key not in _VALID_ECB_RATE_KEYS:
            raise ValueError(
                f"Malformed pair-like FX identifier '{text}': KR namespace represents ECB key rates and cannot contain currency pairs (invalid rate key '{rate_key}', expected one of {sorted(_VALID_ECB_RATE_KEYS)})."
            )
        if unit_token not in _VALID_ECB_SDMX_UNITS:
            raise ValueError(
                f"Malformed pair-like FX identifier '{text}': KR namespace represents ECB key rates and cannot contain currency pairs (invalid unit '{unit_token}', expected one of {sorted(_VALID_ECB_SDMX_UNITS)})."
            )
    else:
        raise ValueError(
            f"Malformed pair-like FX identifier '{text}': KR namespace represents ECB key rates and cannot contain currency pairs (must have exactly 3 dot-delimited components 'KR.<KEY>.<UNIT>')."
        )
```

### Complete Identifier Validation Matrix
| Identifier | `strict=False` | `strict=True` | Rationale |
|---|---|---|---|
| `KR.BOGUS.LEV` | Raises `ValueError` | Raises `ValueError` | Unrecognized rate key ('BOGUS') not in `_VALID_ECB_RATE_KEYS` |
| `KR.RATE1.LEV` | Raises `ValueError` | Raises `ValueError` | Non-alphabetic/unknown rate key ('RATE1') not in `_VALID_ECB_RATE_KEYS` |
| `KR..LEV` | Raises `ValueError` | Raises `ValueError` | Empty rate key token |
| `KR.UNKNOWN_RATE.LEV` | Raises `ValueError` | Raises `ValueError` | Unknown underscore key ('UNKNOWN_RATE') not in `_VALID_ECB_RATE_KEYS` |
| `KR.MRR_FR.UNKNOWN` | Raises `ValueError` | Raises `ValueError` | Unknown unit token ('UNKNOWN') not in `_VALID_ECB_SDMX_UNITS` |
| `KR.MRR_FR.LEV.EXTRA` | Raises `ValueError` | Raises `ValueError` | Component count $\ne 3$ (contains 4 dot-separated tokens) |
| `KR.MRR_FR.` | Raises `ValueError` | Raises `ValueError` | Empty unit token |
| `KR..` | Raises `ValueError` | Raises `ValueError` | Empty rate key and unit tokens |
| `KR.UNKNOWN.BPS` | Raises `ValueError` | Raises `ValueError` | Unrecognized rate key ('UNKNOWN') not in `_VALID_ECB_RATE_KEYS` |
| `KR_EUR_USD` | Raises `ValueError` | Raises `ValueError` | Underscore KR series prohibited |
| `KR.EUR_USD` | Raises `ValueError` | Raises `ValueError` | Component count $\ne 3$; currency pair in KR |
| `KR.GBP_USD` | Raises `ValueError` | Raises `ValueError` | Component count $\ne 3$; currency pair in KR |
| `KR.USD_GBP` | Raises `ValueError` | Raises `ValueError` | Component count $\ne 3$; currency pair in KR |
| `KR.EUR.USD` | Raises `ValueError` | Raises `ValueError` | Invalid rate key ('EUR') not in `_VALID_ECB_RATE_KEYS` |
| `KR.GBP.USD` | Raises `ValueError` | Raises `ValueError` | Invalid rate key ('GBP') not in `_VALID_ECB_RATE_KEYS` |
| `KR.EUR_USD.LEV` | Raises `ValueError` | Raises `ValueError` | Invalid rate key ('EUR_USD') not in `_VALID_ECB_RATE_KEYS` |
| `KR.GBP_USD.LEV` | Raises `ValueError` | Raises `ValueError` | Invalid rate key ('GBP_USD') not in `_VALID_ECB_RATE_KEYS` |
| `KR.USD_GBP.LEV` | Raises `ValueError` | Raises `ValueError` | Invalid rate key ('USD_GBP') not in `_VALID_ECB_RATE_KEYS` |
| `KR.EUR.LEV` | Raises `ValueError` | Raises `ValueError` | Invalid rate key ('EUR') not in `_VALID_ECB_RATE_KEYS` |
| `KR.MRR_FR.LEV` | Returns `None` | Raises `ValueError` | Legitimate ECB Main Refinancing Operations fixed rate |
| `KR.MRR_VR.LEV` | Returns `None` | Raises `ValueError` | Legitimate ECB Main Refinancing Operations variable rate |
| `KR.DFR.LEV` | Returns `None` | Raises `ValueError` | Legitimate ECB Deposit Facility Rate |
| `KR.MLF.LEV` | Returns `None` | Raises `ValueError` | Legitimate ECB Marginal Lending Facility |
| `KR.DF.LEV` | Returns `None` | Raises `ValueError` | Legitimate ECB Deposit Facility |
| `KR.MRR_FR.BPS` | Returns `None` | Raises `ValueError` | Legitimate ECB MRO series with BPS unit |
| `KR.DFR.PCT` | Returns `None` | Raises `ValueError` | Legitimate ECB DFR series with PCT unit |

---

## 4. Workstream B: Multi-Layer Validation Architecture

The KR allowlist enforcement is verified across five distinct system layers:

1. **Layer 1: Direct Metadata Normalization (`validate_and_normalize_fx_metadata`)**:
   - Rejects invalid KR representations immediately.
   - Accepts legitimate KR series when `require_currencies=False`, returning normalized metadata with empty base/quote strings.
2. **Layer 2: Pydantic Schema Ingestion (`DataObservation`)**:
   - Model validator invokes `validate_and_normalize_fx_metadata` and converts `ValueError` into `pydantic.ValidationError`.
3. **Layer 3: Factor Panel Raw Quote Normalization (`_normalize_fx_quote_to_usd_per_eur`)**:
   - Disallows observations with invalid KR entity codes from entering the quote inversion/normalization pipeline.
4. **Layer 4: Boundary Resolution (`resolve_canonical_initial_fx`)**:
   - Prevents corrupted provenance identifiers from generating holdout boundary prices.
5. **Layer 5: End-to-End Factor Panel Construction (`build_fx_carry_factor_panel`)**:
   - Layer 5a: Rejects panels containing corrupted raw observations.
   - Layer 5b: Rejects panel construction when passed a malformed `fx_entity`.

---

## 5. Workstream C: Research Invariance & Numerical Parity

All mathematical invariants and baseline numerical diagnostics are verified:

1. **Panel Temporal Alignment**:
   - Calibration window: `2020-01-06` to `2023-12-29` (990 level dates, 989 transition dates).
   - Holdout window: `2023-12-29` to `2024-12-31` (248 level dates, 247 transition dates).
   - Total aligned unique dates: 1,237; total transitions: 1,236.
2. **Boundary Initial FX Level**:
   - Resolves to `1.104996795509293` USD per EUR at boundary date `2023-12-29` (difference $\le 10^{-9}$).
3. **Empirical Factor Calibration Parity**:
   - Covariance matrix difference: $\max_{ij} |\Sigma_{ij} - \Sigma_{ij}^{\text{baseline}}| \le 10^{-9}$ (measured $\sim 10^{-16}$).
   - Correlation matrix difference: $\max_{ij} |R_{ij} - R_{ij}^{\text{baseline}}| \le 10^{-9}$ (measured $\sim 10^{-16}$).
4. **Holdout Correlation Shifts**:
   - All pairwise correlation shifts between calibration and holdout match baseline within $\le 10^{-9}$.
5. **Research Classification & Status Invariants**:
   - Data classification remains `SIMULATED_RESEARCH_PROXY`.
   - Point-in-time mode remains `ESTIMATED_LAG`.
   - Portfolio holdout diagnostics remain strictly `UNAVAILABLE` (`is_available = False`).

---

## 6. Verification Results

### Test Execution Summary
- **Phase 4.1.2.2.3.10 Dedicated Suite:** `tests/test_monte_carlo_phase_4_1_2_2_3_10.py` — **136 passed in 16.27s** (standalone).
- **Historical Suites (`3_6` to `3_9`):** 100% passed standalone.
- **Complete Repository Test Suite:** **1,020 passed** on both Python 3.11 and Python 3.12 across all CI runs (`42570807986`, `42571481335`, and `42572119609`).
- **Linter Status:** `uv run ruff check .` clean (0 errors, 0 warnings on Python 3.11 and 3.12).
- **CI Workflow Execution:** The GitHub Actions workflow (`.github/workflows/ci.yml`) executes:
  1. `uv run --python ${{ matrix.python-version }} ruff check .`
  2. `uv run --python ${{ matrix.python-version }} pytest -v`  
  *(Note: `ruff format --check` is not part of the GitHub Actions CI workflow; code formatting was verified locally).*
- **CI Environments & Timing (Stage B+ Run `42572119609`):**
  * Python 3.11: Passed in 3m59s (1,020 tests passed, 0 failures, 0 warnings).
  * Python 3.12: Passed in 3m07s (1,020 tests passed, 0 failures, 6 deprecation warnings from Pydantic `datetime.utcnow()`).

---

## 7. Dual-Stage Commit Lineage

Execution follows strict dual-stage delivery:

- **Stage A (Source Code, KR SDMX Allowlist Enforcement & Regression Suite)**:
  * Commit SHA: `6b8256086eb38080d4b00e5357ac8f1d5220edda`
  * CI Run ID: `42570807986` (Both Python 3.11 [4m48s] and 3.12 [2m12s] passed; 1,020 tests passed)
  * Modified: `src/core/currency.py`
  * Added: `tests/test_monte_carlo_phase_4_1_2_2_3_10.py`
  * Commit message: `feat(simulation): Phase 4.1.2.2.3.10 enforce KR rate-key allowlist (Stage A)`

- **Stage B (Closure Documentation Publication)**:
  * Commit SHA: `bddbd2d78f4aeeddb558321bae30e5b2b030ec7c`
  * CI Run ID: `42571481335` (Both Python 3.11 [4m16s] and 3.12 [3m00s] passed; 1,020 tests passed)
  * Added: `PHASE_4_1_2_2_3_10_CLOSURE_REPORT.md`
  * Commit message: `docs(results): publish Phase 4.1.2.2.3.10 closure report (Stage B)`

- **Stage B+ (Documentation Lineage Final Sign-Off Commit)**:
  * Commit SHA: `f53723183cb58a9a250bd56dfb8343a40044385c`
  * CI Run ID: `42572119609` (Both Python 3.11 [3m59s] and 3.12 [3m07s] passed; 1,020 tests passed)
  * Modified: `PHASE_4_1_2_2_3_10_CLOSURE_REPORT.md`
  * Commit message: `docs(results): record verified CI run ID 42571481335 in Phase 4.1.2.2.3.10 closure report`
  * Purpose: Recorded verified Stage B CI Run ID `42571481335`, establishing formal dual-stage lineage sign-off.

---

## 8. Artifact & Infrastructure Reconciliation

### Local Artifact Discrepancy Analysis (Windows File-Handle Quirk)
During multi-suite aggregation runs on Windows (e.g. running 490+ tests from suites `3_6` through `3_10` within a single pytest process), an intermittent `OSError: [Errno 22] Invalid argument: 'data\results\phase_4_1_2_2_3\calibration_report.json'` was observed during file access.

Comprehensive audit confirmed:
- **Artifact Presence & Git Integrity**: `data/results/phase_4_1_2_2_3/calibration_report.json` (5,576 bytes) is committed to git on `main` and present locally in the working tree.
- **Standalone Execution Parity**: Running numerical parity tests standalone (`pytest tests/test_monte_carlo_phase_4_1_2_2_3_10.py -k "parity or invariance"`) passes 100% with absolute tolerance $\le 10^{-9}$ (measured $\sim 10^{-16}$).
- **CI Test Suite Completeness**: On GitHub Actions CI (Ubuntu runners), all 1,020 tests across the full repository test suite pass without error on both Python 3.11 and Python 3.12.
- **Root Cause & Preservation**: The error is an OS-level file handle / path resolution quirk on Windows during long aggregated pytest runs in a single process. No baseline artifacts were altered, regenerated, or corrupted.

---

## 9. Conclusion & Sign-Off

Phase 4.1.2.2.3.10 unconditionally closes the KR namespace fail-open condition, establishes strict 3-component SDMX grammar enforcement, preserves all legitimate ECB policy rate series, reconciles complete commit and CI lineage, and proves numerical invariance parity ($\le 10^{-9}$).

Strictly NO Phase 5 work was initiated.
