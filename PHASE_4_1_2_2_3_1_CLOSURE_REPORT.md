# Phase 4.1.2.2.3.1 — Fail-Closed Canonical Boundary-Level Resolution Closure
## Final Engineering & Research Integrity Closure Report

**The Infinite Money Glitch Detector**  
**Core principle:** *Mathematics first. Data second. Prediction third. AI last.*  
**Status:** COMPLETE & INDEPENDENTLY REPRODUCIBLE  
**Data Classification:** `SIMULATED_RESEARCH_PROXY`  
**Point-in-Time Policy:** `ESTIMATED_LAG`  
**Portfolio Holdout Classification:** `UNAVAILABLE`  

---

## 1. Executive Summary & Engineering Baselines

Phase 4.1.2.2.3.1 hardens `generate_holdout_predictive_paths()` against silently incorrect initial FX and interest-rate values when canonical factor levels are missing or when raw-level fallback logic is invoked.

In Phase 4.1.2.2.3, the primary canonical-data execution path was correctly aligned to the 2023-12-29 calibration boundary ($H + 1 = 248$ levels, 248 synchronized dates). However, the residual fallback logic in `src/simulation/monte_carlo/holdout.py` permitted unverified raw-level values to be used as canonical initial levels:
- Raw FX was used without verifying quote convention, risking silent confusion between raw `EUR_per_USD` and canonical `USD_per_EUR`.
- Raw interest rates were divided by 100 without verifying unit metadata, risking distortion if decimal or basis-point values were provided.
- Investment yield selection permitted ambiguous sovereign yield indicators, risking silent substitution of the 3-month series (`DGS3MO`) for the required 1-month series (`DGS1MO`).

Phase 4.1.2.2.3.1 eliminates these vulnerabilities by replacing naive fallbacks with three modular, fail-closed resolution functions:
1. `resolve_canonical_initial_fx()`
2. `resolve_canonical_initial_borrowing_rate()`
3. `resolve_canonical_initial_investment_rate()`

Each function prefers verified canonical levels, permits fallback only under explicit and authorized metadata, and fails closed (`ValueError`) upon encountering missing, ambiguous, or unsupported units. Furthermore, inferring quote direction from numerical magnitude is strictly prohibited, and silent substitution of sovereign yield tenors is blocked.

### Engineering Baseline & Lineage

| Attribute | Phase 4.1.2.2.3 Predecessor | Phase 4.1.2.2.3.1 Current State |
|---|---|---|
| **Stage A Source Commit** | `790e1e1bae8b3e9ead0300cfc80abd897d89a746` | `b115393216be53da61be58dabfaf3fae42582161` |
| **Stage B Documentation Commit** | `c477023c94ea32bfd33d2bd3e06c156e96b2a7fd` | `78a8c5d789acb3cac079f5f984b8c48c8daefbc4` |
| **Research Outputs Commit** | `c477023c94ea32bfd33d2bd3e06c156e96b2a7fd` | *None (Phase 4.1.2.2.3 artifacts invariant & preserved)* |
| **CI Run ID** | `42453531306` | `42458413071` ([Run URL](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/actions/runs/42458413071)) |
| **Test Suite Baseline** | 424 passed (Python 3.11 & 3.12) | **440 passed** (16 new tests, 0 failures, 0 regressions) |
| **Linter Status** | Ruff clean (0 errors) | **Ruff clean** (0 errors, 0 warnings) |
| **Research Classification** | `SIMULATED_RESEARCH_PROXY` | `SIMULATED_RESEARCH_PROXY` |
| **PIT Policy Mode** | `ESTIMATED_LAG` | `ESTIMATED_LAG` |
| **Portfolio Holdout Status** | `UNAVAILABLE` | `UNAVAILABLE` |
| **FX Boundary Resolution** | Unsafe raw fallback | **Fail-closed canonical resolver (`resolve_canonical_initial_fx`)** |
| **Borrowing Rate Boundary** | Naive `/ 100` fallback | **Fail-closed unit-verified resolver (`resolve_canonical_initial_borrowing_rate`)** |
| **Investment Yield Tenor** | Ambiguous indicator search | **Strict 1M enforcement (`DGS1MO`); 3M substitution prohibited** |
| **Holdout Initial Spot ($S_0$)** | Canonical `1.104997` USD/EUR | **Canonical `1.104997` USD/EUR (invariant)** |
| **Holdout Initial Borrowing ($r_b$)** | Boundary `0.0450` (4.50%) | **Boundary `0.0450` (4.50%) (invariant)** |
| **Holdout Initial Investment ($r_i$)**| Boundary `0.0555` (5.55%) | **Boundary `0.0555` (5.55%) (invariant)** |
| **Scenario Date Alignment** | 248 dates, 248 levels, 247 steps | **248 dates, 248 levels, 247 steps (strictly preserved)** |
| **Calendar Validation** | Passed `JOINT_TARGET2_FED` & Proxy | **Passed `JOINT_TARGET2_FED` & Proxy** |

---

## 2. Workstream A — Fail-Closed Canonical FX Boundary Resolution

### Specification & Rules
The strategy requires initial FX spot in canonical units:
$$\text{Units of USD per 1 EUR}$$

Raw source providers (such as Frankfurter API) supply exchange rates quoted as units of EUR per 1 USD ($0.91274$). The previous fallback blindly used `raw_levels[fx_key][-1]`, which would have initialized holdout simulation paths at $0.91274$ instead of the true spot level of $1.095602$ or canonical boundary level of $1.104997$.

### Implementation: `resolve_canonical_initial_fx()`
In `src/simulation/monte_carlo/holdout.py`:
1. **Target Factor**: Exact factor ID `FX_EUR_USD_LOGRET`.
2. **Canonical Preference**: If present in `calibration_panel.canonical_levels`, returns `float(canonical_levels[fx_key][-1])` directly ($1.1049967955$).
3. **Authorized Raw Fallback**: If canonical levels are missing, falls back to `calibration_panel.raw_levels` **only** if explicit quote metadata is present in `row_provenance` or `MarketFactor.original_unit`:
   - `USD_per_EUR`: Preserved as-is.
   - `EUR_per_USD`: Inverted via `_normalize_fx_quote_to_usd_per_eur(obs)` ($1.0 / \text{raw\_value}$).
4. **Fail-Closed Guarantees**:
   - Rejects missing, empty, or unsupported quote conventions (`ValueError`).
   - Strictly prohibits inferring quote direction from numerical magnitude.
   - Enforces finite positivity ($S_0 > 0$).

---

## 3. Workstream B — Fail-Closed EUR Borrowing Rate Boundary Resolution

### Specification & Rules
The strategy requires initial borrowing rates as an annual decimal:
$$r_b = \frac{\text{percentage points}}{100}$$

In canonical factor panels, `RATE_DIFF_EUR_BORROW_BPS` stores levels in percentage points ($4.50$). However, raw sources may report rates in percentage points (`percent`), decimals (`decimal`), or basis points (`bps`). The previous fallback divided any raw value by 100 without checking units.

### Implementation: `resolve_canonical_initial_borrowing_rate()`
In `src/simulation/monte_carlo/holdout.py`:
1. **Target Factor**: Exact factor ID `RATE_DIFF_EUR_BORROW_BPS`.
2. **Canonical Preference**: Converts canonical percentage points to annual decimal via `percentage_points / 100.0` ($4.50\% \to 0.0450$).
3. **Authorized Raw Fallback**: If canonical levels are missing, inspects `row_provenance` or `MarketFactor.original_unit`:
   - `percent`: Converted to decimal via `value / 100.0`.
   - `decimal`: Preserved as-is.
   - `bps`: Converted to decimal via `value / 10000.0`.
4. **Fail-Closed Guarantees**:
   - Rejects missing, empty, or unrecognized rate units (`ValueError`).
   - Enforces finite non-negativity ($r_b \ge 0$).

---

## 4. Workstream C — Fail-Closed USD Investment Yield Boundary Resolution & Tenor Enforcement

### Specification & Rules
The cash-flow reinvestment leg of the EUR/USD carry trade requires the 1-month sovereign investment yield:
$$\text{Required Series: } \text{DGS1MO } (\text{Factor ID: } \text{YIELD\_DIFF\_USD\_1M\_BPS})$$

The 3-month series (`DGS3MO`) is retained in the factor panel solely for sovereign term-structure and spread diagnostics. Under no circumstances may `DGS3MO` be silently substituted for `DGS1MO` as the scenario investment rate.

### Implementation: `resolve_canonical_initial_investment_rate()`
In `src/simulation/monte_carlo/holdout.py`:
1. **Target Factor**: Exact factor ID `YIELD_DIFF_USD_1M_BPS`.
2. **Tenor Validation**: Prohibits factors with series ID containing `3M` or `3MO`. If only 3-month sovereign yield is available, fails closed with an explicit error:
   ```
   ValueError: Cannot resolve initial USD investment yield: required 1-month series ('YIELD_DIFF_USD_1M_BPS' / DGS1MO) is missing from calibration panel. Silent substitution of DGS3MO or other sovereign yield tenors is strictly prohibited.
   ```
3. **Canonical Preference**: Converts canonical percentage points to annual decimal via `percentage_points / 100.0` ($5.55\% \to 0.0555$).
4. **Authorized Raw Fallback**: Confirms 1-month series identity and normalizes rate via `_normalize_rate_to_decimal(obs)`.
5. **Fail-Closed Guarantees**:
   - Rejects missing or unknown unit metadata (`ValueError`).
   - Enforces finite non-negativity ($r_i \ge 0$).

---

## 5. Warning Elimination & Numerical Stability

During test suite hardening, two non-fatal warning classes were identified and cleanly eliminated:
1. **SciPy Catastrophic Cancellation Warnings**: In `src/simulation/monte_carlo/calibration.py` (`compute_quantiles`), when evaluating synthetic constant test series where $\sigma < 10^{-12}$, SciPy emitted precision loss warnings during skewness and kurtosis calculations. Added explicit zero-variance detection to set skewness and kurtosis analytically to `0.0`.
2. **NumPy Divide-by-Zero Warnings**: In `calibrate_factor_panel` and `evaluate_factor_holdout_diagnostics`, calculating Pearson correlation matrices on constant synthetic factor series produced $0/0$ division warnings. Wrapped correlation calculations with local `np.errstate(divide="ignore", invalid="ignore")` and `np.nan_to_num(nan=0.0)`.

---

## 6. Verification & Regression Test Suite Summary

The dedicated test suite `tests/test_monte_carlo_phase_4_1_2_2_3_1.py` implements 16 comprehensive regression tests covering all 12 mandate requirements:

| # | Test Requirement | Test Method | Result |
|---|---|---|:---:|
| 1 | Canonical USD/EUR FX initialization unchanged | `test_canonical_usd_eur_unchanged` | **PASSED** |
| 2 | Raw EUR/USD inverted when authorized | `test_raw_eur_usd_inverted_with_authorized_metadata` | **PASSED** |
| 3 | Raw USD/EUR preserved when authorized | `test_raw_usd_eur_preserved_with_authorized_metadata` | **PASSED** |
| 4 | Ambiguous FX quote conventions fail closed | `test_ambiguous_quote_metadata_fails_closed` | **PASSED** |
| 5 | Percentage-point rates convert to decimal | `test_canonical_percentage_points_to_decimal` | **PASSED** |
| 6 | Decimal, percent, and bps raw rates normalized | `test_raw_rate_units_normalized_correctly` | **PASSED** |
| 7 | Missing/unknown raw rate units fail closed | `test_missing_or_unknown_borrowing_rate_unit_fails_closed` | **PASSED** |
| 8 | Missing DGS1MO prohibits DGS3MO substitution | `test_dgs3mo_silent_substitution_strictly_prohibited` | **PASSED** |
| 9 | Boundary state matches established values | `test_genuine_data_boundary_state_consistency` | **PASSED** |
| 10 | 248 dates, 248 levels, 247 transitions invariant | `test_genuine_data_boundary_state_consistency` | **PASSED** |
| 11 | Passes both calendar validation engines | `test_genuine_data_boundary_state_consistency` | **PASSED** |
| 12 | Portfolio holdout remains strictly UNAVAILABLE | `test_portfolio_holdout_remains_strictly_unavailable` | **PASSED** |
| 13 | Non-positive / non-finite FX fails closed | `test_non_positive_or_non_finite_fx_fails_closed` | **PASSED** |
| 14 | Raw 1M investment yield normalized with units | `test_raw_1m_yield_normalized_with_authorized_units` | **PASSED** |
| 15 | Missing investment yield units fail closed | `test_missing_or_unknown_investment_yield_unit_fails_closed` | **PASSED** |
| 16 | Path generator integration fails closed on raw ambiguity | `test_path_generation_fails_closed_on_unauthorized_raw_metadata` | **PASSED** |

### Full Test Suite Results
```
======================= 440 passed in 96.19s (0:01:36) ========================
```
- Total tests: **440 passed**, 0 failed.
- Linter: **`ruff check .` passed with 0 errors and 0 warnings**.

---

## 7. Empirical Invariance & Cross-Model Risk Breakdown

Execution of the full research pipeline (`examples/run_monte_carlo_research.py`) confirms that established simulation results and risk metrics are completely preserved:

### Cross-Model Risk & Return Distribution ($N=1,000$, $H=252$, $\text{seed}=42$)

| Model Architecture | Median Return | Mean Return | Volatility | VaR (95%) | CVaR (95%) | Prob(Loss) | Prob(DD $\ge$ 10%) | Checkpoint Stability |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Multivariate Gaussian** | +1.75% | +1.98% | 4.01% | -4.53% | -5.97% | 31.9% ($\pm$1.47%) | 0.3% | `ACHIEVED` |
| **Moving-Block Bootstrap (20d)** | +2.25% | +2.23% | 4.01% | -4.41% | -5.93% | 27.9% ($\pm$1.42%) | 0.7% | `ACHIEVED` |
| **IID Bootstrap** | +1.99% | +2.01% | 3.99% | -4.25% | -6.26% | 32.1% ($\pm$1.48%) | 0.4% | `ACHIEVED` |
| **Stationary Bootstrap (20d)** | +2.06% | +2.00% | 3.97% | -4.41% | -5.82% | 31.0% ($\pm$1.46%) | 0.3% | `ACHIEVED` |
| **Multivariate Student-t** | +1.60% | +1.88% | 3.68% | -3.77% | -6.38% | 29.2% ($\pm$1.44%) | 0.8% | `ACHIEVED` |
| **Regime-Conditioned Bootstrap** | +1.71% | +1.60% | 3.93% | -5.21% | -6.98% | 34.1% ($\pm$1.50%) | 1.5% | `NOT_ACHIEVED` |

### 2024 Holdout Diagnostics
- Realized Cumulative FX Return: **-5.98%** (22.9th percentile).
- Realized FX Volatility: **6.18%** (0.6th percentile, `NORMAL_VOLATILITY`).
- Realized Maximum Drawdown: **-7.21%** (64.9th percentile).
- Strategy Portfolio Holdout: **`UNAVAILABLE`** (truthfully declared).

---

## 8. Remaining Boundaries & Research Protocol

1. **Portfolio Holdout**: Remains classified as `UNAVAILABLE`. No live executions, broker fills, or order-book executions occurred during 2024. The strategy remains classified as `SIMULATED_RESEARCH_PROXY`.
2. **Phase 5 Not Started**: Phase 5 (live execution integrations, production brokers, execution algorithms) has **not** begun. No new strategy features or optimization loops were introduced.
3. **Fail-Closed Guarantees**: A missing or ambiguous boundary level immediately halts path generation with an informative error rather than silently defaulting to inaccurate market conditions.