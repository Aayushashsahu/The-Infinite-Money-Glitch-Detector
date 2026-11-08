# Phase 4.1.2.2.3.2 — Per-Observation Provenance Integrity & Audit-Lineage Reconciliation Closure
## Final Engineering & Research Integrity Closure Report

**The Infinite Money Glitch Detector**  
**Core principle:** *Mathematics first. Data second. Prediction third. AI last.*  
**Status:** COMPLETE & INDEPENDENTLY REPRODUCIBLE  
**Data Classification:** `SIMULATED_RESEARCH_PROXY`  
**Point-in-Time Policy:** `ESTIMATED_LAG`  
**Portfolio Holdout Classification:** `UNAVAILABLE`  

---

## 1. Executive Summary & Engineering Baselines

Phase 4.1.2.2.3.2 resolves subtle fail-closed metadata vulnerabilities in the holdout boundary-level resolvers and eliminates the risk of mistaking factor-level contract declarations for actual observation-level quote provenance.

In Phase 4.1.2.2.3.1, modular resolvers (`resolve_canonical_initial_fx`, `resolve_canonical_initial_borrowing_rate`, and `resolve_canonical_initial_investment_rate`) were introduced to prevent naive raw fallbacks. However, factor-level metadata (such as `MarketFactor.original_unit="USD_per_EUR"`) remained accessible as a fallback when observation provenance was missing. In such cases, unverified raw `EUR_per_USD` values (such as Frankfurter's `0.91274`) could have been mistakenly treated as canonical `USD_per_EUR`.

Phase 4.1.2.2.3.2 enforces strict observation-level provenance:
1. **Observation-Level Raw Unit Precedence**: The resolver strictly requires genuine observation-level row provenance (`FactorRowProvenance`). Falling back to `MarketFactor.original_unit` is prohibited and fails closed (`ValueError`).
2. **Reconciliation Guardrails**: The raw level value must reconcile with `prov.raw_value` ($|v_{\text{raw}} - v_{\text{prov}}| \le 10^{-9}$), and the provenance observation date must match the requested calibration boundary date.
3. **Contradictory Metadata Guardrails**: Contradictory currency or quote metadata (e.g. invalid currency pairs outside EUR/USD, identical base and quote currencies) fail closed immediately.
4. **Strict Tenor Enforcement**: USD investment yield requires explicit 1-month tenor evidence in observation provenance (`prov.series_id == "DGS1MO"`). Manufacturing or defaulting series identifiers is prohibited.
5. **Correlation Semantics**: Undefined linear correlations caused by zero-variance series are preserved as `NaN` rather than misleadingly masked as `0.0`. A `correlation_validity_mask` tracks valid pairwise correlations explicitly.
6. **Audit Lineage Reconciliation**: Corrects the commit lineage of Phase 4.1.2.2.3.1, clearly separating source commits, documentation commits, and invariant research outputs.

### Engineering Baseline & Lineage

| Attribute | Phase 4.1.2.2.3.1 Predecessor | Phase 4.1.2.2.3.2 Current State |
|---|---|---|
| **Stage A Source Commit** | `b115393216be53da61be58dabfaf3fae42582161` | `3b08823e17eeebf64b7960aed0286fe13479abc3` |
| **Stage B Documentation Commit** | `78a8c5d789acb3cac079f5f984b8c48c8daefbc4` | *Recorded in Stage B commit* |
| **Research Outputs Commit** | *None (Phase 4.1.2.2.3 artifacts invariant)* | *None (Phase 4.1.2.2.3 artifacts invariant & preserved)* |
| **Predecessor CI Run ID** | `42458413071` | `42458413071` ([Run URL](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/actions/runs/42458413071)) |
| **Test Suite Baseline** | 440 passed (Python 3.11 & 3.12) | **460 passed** (20 new tests, 0 failures, 0 regressions) |
| **Linter Status** | Ruff clean (0 errors) | **Ruff clean** (0 errors, 0 warnings) |
| **Research Classification** | `SIMULATED_RESEARCH_PROXY` | `SIMULATED_RESEARCH_PROXY` |
| **PIT Policy Mode** | `ESTIMATED_LAG` | `ESTIMATED_LAG` |
| **Portfolio Holdout Status** | `UNAVAILABLE` | `UNAVAILABLE` |
| **FX Boundary Resolution** | Resolver with factor fallback risk | **Strict per-observation provenance required; factor defaults fail closed** |
| **Borrowing Rate Boundary** | Unit verified with factor fallback risk | **Strict per-observation provenance required; factor defaults fail closed** |
| **Investment Yield Tenor** | Series check with default fallback risk | **Strict per-observation 1M evidence (`DGS1MO`); no manufactured defaults** |
| **Correlation Semantics** | `np.nan_to_num(..., nan=0.0)` | **Mathematical `NaN` preserved; explicit `correlation_validity_mask` added** |
| **Holdout Initial Spot ($S_0$)** | Canonical `1.104997` USD/EUR | **Canonical `1.104997` USD/EUR (invariant)** |
| **Holdout Initial Borrowing ($r_b$)** | Boundary `0.0450` (4.50%) | **Boundary `0.0450` (4.50%) (invariant)** |
| **Holdout Initial Investment ($r_i$)**| Boundary `0.0555` (5.55%) | **Boundary `0.0555` (5.55%) (invariant)** |
| **Scenario Date Alignment** | 248 dates, 248 levels, 247 steps | **248 dates, 248 levels, 247 steps (strictly preserved)** |
| **Calendar Validation** | Passed `JOINT_TARGET2_FED` & Proxy | **Passed `JOINT_TARGET2_FED` & Proxy** |

---

## 2. Workstream A — Per-Observation FX Raw-Level Provenance

### Specification & Defect Analysis
In `FactorPanel`, the factor definition `MarketFactor.original_unit` is statically set to `"USD_per_EUR"`. However, `raw_levels` stores the exact raw observation from upstream providers (e.g., Frankfurter's `0.91274 EUR_per_USD`).

When canonical levels were missing, fallback logic previously fell back to `factor_meta.original_unit` when row provenance was absent. This risked interpreting raw `0.91274` as canonical `USD_per_EUR`, corrupting the initial spot level to $0.91274$ instead of the true canonical level $1.095602$ (or boundary level $1.104997$).

### Implementation in `src/simulation/monte_carlo/holdout.py`
In `resolve_canonical_initial_fx()`:
1. Canonical levels are preferred.
2. If falling back to raw levels, genuine observation-level row provenance (`calibration_panel.row_provenance[fx_key]`) is **strictly mandatory**. If missing, the resolver fails closed (`ValueError`).
3. Reconciles raw level value with `prov.raw_value`:
   $$|v_{\text{raw}} - \text{prov.raw\_value}| \le 10^{-9}$$
4. Reconciles provenance date with requested boundary date:
   $$\text{prov.observation\_date} == \text{boundary\_date}$$
5. Verifies currencies: `base_currency` and `quote_currency` must belong to `{"USD", "EUR"}` and cannot be identical.
6. Rejects missing or unsupported quote conventions (`prov.raw_unit` must explicitly be `"USD_per_EUR"` or `"EUR_per_USD"`).
7. Uses `_normalize_fx_quote_to_usd_per_eur` to normalize without inferring quote direction from numerical magnitude.

---

## 3. Workstream B — Per-Observation Rate Raw-Level Provenance

### Implementation in `src/simulation/monte_carlo/holdout.py`
In `resolve_canonical_initial_borrowing_rate()` and `resolve_canonical_initial_investment_rate()`:
1. Target canonical levels are converted via `percentage_points / 100.0`.
2. When falling back to raw levels, factor defaults (`MarketFactor.original_unit`) cannot silently authorize rate unit conversion. Observation-level row provenance is required.
3. Raw value reconciliation:
   $$|v_{\text{raw}} - \text{prov.raw\_value}| \le 10^{-9}$$
4. Observation date reconciliation:
   $$\text{prov.observation\_date} == \text{boundary\_date}$$
5. Authorized units strictly enforced:
   - `percent`, `pct`, `%`: $v_{\text{raw}} / 100.0$
   - `decimal`, `dec`, `ratio`: $v_{\text{raw}}$
   - `basis_points`, `bps`: $v_{\text{raw}} / 10000.0$
   - Missing, empty, or unknown units fail closed (`ValueError`).

---

## 4. Workstream C — Investment Tenor Evidence & Rejection of Manufactured Defaults

### Implementation in `src/simulation/monte_carlo/holdout.py`
The FX carry strategy model strictly requires 1-month sovereign yields (`DGS1MO`) to match monthly rebalancing liquidity.
1. The resolver searches factor metadata strictly for 1-month indicators (`DGS1MO` or `1M`). Silent substitution of 3-month yields (`DGS3MO`) is blocked.
2. For raw fallbacks, explicit 1-month tenor evidence is required in `prov.series_id` (must contain `DGS1MO`, `1M`, or `1MO`).
3. Rejects manufactured defaults: defaulting `indicator_id = series_id or "DGS1MO"` is completely eliminated. Missing series identifier fails closed (`ValueError`).

---

## 5. Workstream D — Correlation Semantics & Zero-Variance Mathematical Truth

### Mathematical Principle
For any series $X$ with zero variance ($\sigma_X = 0$), the Pearson linear correlation coefficient:
$$\rho_{X, Y} = \frac{\operatorname{Cov}(X, Y)}{\sigma_X \sigma_Y} = \frac{0}{0}$$
is mathematically undefined. Replacing undefined correlation with $0.0$ misrepresents a mathematical singularity as empirical uncorrelatedness.

### Implementation in `src/simulation/monte_carlo/calibration.py` & `holdout.py`
1. **Calibration Validity Mask**: Added `correlation_validity_mask: list[list[bool]]` to `CalibrationReport`.
   - `mask[i][j] = True` if and only if both factor $i$ and factor $j$ exhibit non-zero variance ($\sigma > 10^{-12}$).
   - `mask[i][j] = False` when either factor exhibits zero variance.
2. **Preservation of `NaN`**: In `correlation_matrix`, undefined entries retain `float('nan')` rather than `0.0`.
3. **Explicit Notes**: Detailed explanation added to `sufficiency_notes` in `CalibrationReport`:
   `Factor '{fname}' has zero or near-zero variance ({std}); pairwise linear correlations involving this factor are mathematically undefined.`
4. **Factor Holdout Diagnostics**: In `evaluate_factor_holdout_diagnostics()`, cross-factor correlation shifts involving zero-variance factors record `NaN` in `correlation_shifts` and an explicit entry in `limitations_notes`.
5. **Local Warning Isolation**: All numerical evaluation is wrapped in local `with np.errstate(divide="ignore", invalid="ignore"):` contexts; warnings are never globally suppressed.
6. **Empirical Invariance**: Genuine historical panels (with non-zero variance across all factors) retain 100% valid, invariant correlation matrices.

---

## 6. Workstream E — Commit Lineage Reconciliation of Phase 4.1.2.2.3.1

Phase 4.1.2.2.3.1 documentation was reconciled to eliminate fabricated or non-resolvable commit references:
- **Stage A Source Commit**: `b115393216be53da61be58dabfaf3fae42582161`
- **Stage B Documentation Commit**: `78a8c5d789acb3cac079f5f984b8c48c8daefbc4`
- **Research Outputs Commit**: *None (Phase 4.1.2.2.3 artifacts in `data/results/phase_4_1_2_2_3/` verified invariant and preserved)*
- **CI Run ID**: `42458413071` ([Run URL](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/actions/runs/42458413071))

---

## 7. Verification & Full Test Suite Execution

### Focused Regression Tests (`tests/test_monte_carlo_phase_4_1_2_2_3_2.py`)
```
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamAFXRawProvenance::test_canonical_usd_eur_unchanged PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamAFXRawProvenance::test_missing_provenance_with_factor_default_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamAFXRawProvenance::test_raw_eur_usd_inverted_using_genuine_provenance_metadata PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamAFXRawProvenance::test_raw_usd_eur_preserved_using_genuine_provenance_metadata PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamAFXRawProvenance::test_contradictory_currency_metadata_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamAFXRawProvenance::test_raw_level_and_provenance_value_mismatch_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamAFXRawProvenance::test_provenance_date_and_boundary_date_mismatch_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamBRateRawProvenance::test_canonical_borrowing_and_investment_rates_invariant PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamBRateRawProvenance::test_missing_provenance_with_factor_default_rate_unit_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamBRateRawProvenance::test_explicit_rate_units_normalized_correctly PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamBRateRawProvenance::test_rate_value_and_provenance_mismatch_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamCInvestmentTenorEvidence::test_missing_investment_series_identifier_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamCInvestmentTenorEvidence::test_dgs3mo_provenance_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamCInvestmentTenorEvidence::test_valid_dgs1mo_provenance_normalizes_correctly PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamDCorrelationSemantics::test_constant_factor_series_produces_nan_and_validity_mask PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamDCorrelationSemantics::test_single_factor_zero_variance_edge_case PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamDCorrelationSemantics::test_factor_holdout_diagnostics_preserves_nan_for_zero_variance PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamDCorrelationSemantics::test_genuine_historical_panel_correlation_unchanged PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamEEndToEndPreservation::test_genuine_boundary_state_and_calendar_validation PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_2.py::TestWorkstreamEEndToEndPreservation::test_portfolio_holdout_strictly_unavailable PASSED
============================= 20 passed in 14.24s =============================
```

### Full Repository Test Suite
```
======================= 460 passed in 100.65s (0:01:40) =======================
```
- Total test count: **460 passed** (0 failures, 0 regressions across all modules).
- Linter: **`ruff check .` passed with 0 errors and 0 warnings**.

---

## 8. Empirical Invariance & Cross-Model Risk Preservation

All cross-model Monte Carlo simulation metrics and risk distributions remain 100% invariant under the strengthened provenance and correlation contracts:

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

## 9. Remaining Boundaries & Research Protocol

1. **Portfolio Holdout**: Remains classified as `UNAVAILABLE`. No live executions, broker fills, or order-book executions occurred during 2024. The strategy remains classified as `SIMULATED_RESEARCH_PROXY`.
2. **Phase 5 Not Started**: Phase 5 (live execution integrations, production brokers, execution algorithms) has **not** begun. No new strategy features or optimization loops were introduced.
3. **Fail-Closed Guarantees**: A missing or ambiguous observation-level unit or tenor immediately halts simulation with an informative error rather than silently defaulting to inaccurate factor-level declarations.
