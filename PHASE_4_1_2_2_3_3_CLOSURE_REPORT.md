# Phase 4.1.2.2.3.3 — FX Quote-Convention Reconciliation & Near-Zero Correlation Consistency Closure
## Final Engineering & Research Integrity Closure Report

**The Infinite Money Glitch Detector**  
**Core principle:** *Mathematics first. Data second. Prediction third. AI last.*  
**Status:** COMPLETE & INDEPENDENTLY REPRODUCIBLE  
**Data Classification:** `SIMULATED_RESEARCH_PROXY`  
**Point-in-Time Policy:** `ESTIMATED_LAG`  
**Portfolio Holdout Classification:** `UNAVAILABLE`  

---

## 1. Executive Summary & Engineering Baselines

Phase 4.1.2.2.3.3 eliminates two subtle research-integrity vulnerabilities identified during independent review of Phase 4.1.2.2.3.2:
1. **Contradictory FX Unit/Currency Metadata**: Explicit unit declarations could contradict base/quote currencies without being rejected, or generic provider metadata (`unit="quote_per_base"`) was unhandled by raw boundary resolvers.
2. **Inconsistent Near-Zero Correlation Semantics**: Correlation handling between calibration and holdout diagnostics differed in thresholding and failed to distinguish exact zero variance from near-zero numerical degeneracy.

Additionally, this phase establishes formal, reproducible mathematical evidence proving that all genuine historical calibration parameters, covariance matrices, correlation shifts, and research classifications remain **100% numerically invariant** (maximum absolute difference: $\le 0.00\text{e}+00$).

### Engineering Baseline & Lineage

| Attribute | Phase 4.1.2.2.3.2 Predecessor | Phase 4.1.2.2.3.3 Current State |
|---|---|---|
| **Stage A Source Commit** | `3b08823e17eeebf64b7960aed0286fe13479abc3` | `ce15f0beaf7de9d95eddc36f284bc255c66c36f2` |
| **Stage B Documentation Commit** | `89419286183ee67693f6f3f82e55c303fd849000` | *Recorded in Stage B commit* |
| **Research Outputs Commit** | *Phase 4.1.2.2.3 outputs invariant & preserved* | *Phase 4.1.2.2.3 outputs invariant & preserved* |
| **Predecessor CI Run ID** | `42461225956` | `42461225956` ([Run URL](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/actions/runs/42461225956)) |
| **Test Suite Baseline** | 460 passed (Python 3.11 & 3.12) | **485 passed** (25 new tests, 0 failures, 0 regressions) |
| **Linter Status** | Ruff clean (0 errors) | **Ruff clean** (0 errors, 0 warnings) |
| **Research Classification** | `SIMULATED_RESEARCH_PROXY` | `SIMULATED_RESEARCH_PROXY` |
| **PIT Policy Mode** | `ESTIMATED_LAG` | `ESTIMATED_LAG` |
| **Portfolio Holdout Status** | `UNAVAILABLE` | `UNAVAILABLE` |
| **FX Quotation Contract** | Per-observation provenance check | **Universal `BASE/QUOTE = units of QUOTE per BASE` contract enforced platform-wide** |
| **Provider Unit Support** | Explicit units only | **Native `quote_per_base` supported; missing currency metadata fails closed** |
| **Variance Degeneracy Policy** | `1e-12` in calibration; `0.0` in holdout | **Unified `VARIANCE_DEGENERACY_THRESHOLD = 1e-12` shared across calibration & holdout** |
| **Singularity Distinction** | `std == 0.0` lumped with near-zero | **Exact zero ($\sigma = 0.0$, undefined) explicitly distinguished from near-zero ($0 < \sigma < 10^{-12}$, unreliable)** |
| **Holdout Initial Spot ($S_0$)** | Canonical `1.104997` USD/EUR | **Canonical `1.104997` USD/EUR (max diff: $0.00\text{e}+00$)** |
| **Holdout Initial Borrowing ($r_b$)** | Boundary `0.0450` (4.50%) | **Boundary `0.0450` (4.50%) (max diff: $0.00\text{e}+00$)** |
| **Holdout Initial Investment ($r_i$)**| Boundary `0.0555` (5.55%) | **Boundary `0.0555` (5.55%) (max diff: $0.00\text{e}+00$)** |
| **Scenario Calendar Alignment** | 248 dates, 248 levels, 247 steps | **248 dates, 248 levels, 247 steps (strictly preserved)** |
| **Calendar Validation** | Passed `JOINT_TARGET2_FED` & Proxy | **Passed `JOINT_TARGET2_FED` & Proxy** |

---

## 2. Workstream A — Strict FX Unit/Currency Consistency

### Specification & Defect Analysis
The platform quotation convention is canonically defined as:
$$\text{BASE/QUOTE} = \text{units of QUOTE per one unit of BASE}$$

| Base Currency | Quote Currency | Canonical Unit Expression | Nominal Value Meaning |
|---|---|---|---|
| `EUR` | `USD` | `USD per EUR` (`USD_per_EUR`) | 1 EUR = $X$ USD ($\approx 1.09$) |
| `USD` | `EUR` | `EUR per USD` (`EUR_per_USD`) | 1 USD = $Y$ EUR ($\approx 0.91$) |

Prior to Phase 4.1.2.2.3.3:
1. `DataObservation` permitted explicit unit metadata (`unit="EUR_per_USD"`) on an observation declaring `base_currency="EUR"` and `quote_currency="USD"`. This silent contradiction allowed inverted quotes to bypass normalization.
2. Frankfurter returns native observations with `unit="quote_per_base"`. The boundary resolver `resolve_canonical_initial_fx()` lacked support for this generic provider unit, failing when genuine provider metadata was encountered in raw fallbacks.

### Implementation Details
1. **Contradiction Guardrails in `src/data/schemas.py`**:
   `DataObservation` validation now rigorously cross-checks currencies against explicit unit strings. Declaring `unit="EUR_per_USD"` with `base_currency="EUR"` or `quote_currency="USD"` immediately raises a descriptive `ValueError`.
2. **Base/Quote Currency Inference**:
   When `base_currency` or `quote_currency` is absent, `DataObservation` infers them from unambiguous explicit unit declarations (`usd_per_eur` $\rightarrow$ EUR base / USD quote; `eur_per_usd` $\rightarrow$ USD base / EUR quote) before falling back to entity code parsing.
3. **Provider `quote_per_base` Support in `factors.py` & `holdout.py`**:
   `_normalize_fx_quote_to_usd_per_eur()` and `resolve_canonical_initial_fx()` now support `unit in ("quote_per_base", "quotation_per_base", "quote/base")`. Direction is determined strictly from explicit `base_currency` and `quote_currency`:
   - Base `EUR`, Quote `USD`: value is already `USD per EUR` $\rightarrow$ preserved.
   - Base `USD`, Quote `EUR`: value is `EUR per USD` $\rightarrow$ inverted ($1.0 / v$).
   - If base or quote currency is missing or ambiguous, the resolver **fails closed** (`ValueError`). Numerical magnitude is never used to infer quote direction.
4. **Provenance Tracking**:
   `FactorRowProvenance` was extended with `quote_convention: str | None = None` to permanently record whether observations used `quote_per_base` or `base_per_quote`.
5. **Fixture Reconciliation**:
   Raw FX fixtures across `test_monte_carlo_phase_4_1_2_2_2.py`, `test_monte_carlo_phase_4_1_2_2_3_1.py`, and `test_monte_carlo_phase_4_1_2_2_3_2.py` were reconciled so pair codes, base/quote currencies, and raw units strictly adhere to the quotation contract.

---

## 3. Workstream B — Unified Near-Zero Correlation Semantics

### Mathematical Principle
For two time series $X$ and $Y$, the Pearson sample correlation coefficient is defined as:
$$\rho_{X, Y} = \frac{\operatorname{Cov}(X, Y)}{\sigma_X \sigma_Y}$$

1. **Exact Zero Variance ($\sigma = 0.0$)**:
   The denominator is identically zero: $\rho_{X, Y} = \frac{0}{0}$. The correlation coefficient is **mathematically undefined**. Replacing undefined correlation with $0.0$ falsely implies linear independence when in reality no linear relationship can be defined.
2. **Near-Zero Numerical Degeneracy ($0 < \sigma < 10^{-12}$)**:
   The correlation is mathematically defined, but floating-point rounding errors and division by near-zero standard deviations render the result **numerically unreliable**.

### Unified Policy Implementation
1. **Shared Threshold**:
   Centralized `VARIANCE_DEGENERACY_THRESHOLD: float = 1e-12` in `calibration.py` and imported into `holdout.py`.
2. **Variance Classification Helper**:
   `check_factor_variance(series, threshold=1e-12) -> tuple[float, bool, bool]` returns `(std, is_exact_zero, is_near_zero)`.
3. **Calibration Diagnostics (`calibrate_factor_panel`)**:
   - `std == 0.0`: Appends explanatory note that correlation is *mathematically undefined*. Invalid entries set to `NaN`.
   - $0 < \text{std} < 10^{-12}$: Emits warning and appends explanatory note that correlation is *numerically unreliable*. Invalid entries set to `NaN`.
   - `correlation_validity_mask` tracks valid pairwise correlation pairs (`False` for any pair containing a degenerate factor).
4. **Holdout Diagnostics (`evaluate_factor_holdout_diagnostics`)**:
   - Applies the identical `1e-12` threshold to both calibration and holdout factor series.
   - Any cross-factor correlation shift involving degenerate factors is marked as `NaN` in `correlation_shifts`.
   - Diagnostic notes explicitly distinguish mathematically undefined shifts from numerically unreliable shifts.
5. **Warning Scoping**:
   All operations use scoped `with np.errstate(divide="ignore", invalid="ignore"):` contexts without global warning suppression.

---

## 4. Workstream C — Research Result Invariance Evidence

To verify that these integrity enhancements have zero adverse impact on existing empirical findings, we conducted an exhaustive numerical reconciliation of the full historical calibration and holdout experiment.

### Empirical Invariance Verification Table

| Metric / Parameter | Baseline Value | Phase 4.1.2.2.3.3 Value | Max Absolute Difference | Status |
|---|---|---|---|---|
| **Holdout Initial FX ($S_0$)** | `1.1049967955` USD/EUR | `1.1049967955` USD/EUR | `0.00e+00` | **EXACT MATCH** |
| **Holdout Initial Borrowing ($r_b$)** | `0.0450000000` (4.50%) | `0.0450000000` (4.50%) | `0.00e+00` | **EXACT MATCH** |
| **Holdout Initial Investment ($r_i$)** | `0.0555000000` (5.55%) | `0.0555000000` (5.55%) | `0.00e+00` | **EXACT MATCH** |
| **Calibration Observation Count** | `1002` | `1002` | `0` | **EXACT MATCH** |
| **Holdout Observation Count** | `248` | `248` | `0` | **EXACT MATCH** |
| **Calibration Transition Count** | `1001` | `1001` | `0` | **EXACT MATCH** |
| **Holdout Transition Count** | `247` | `247` | `0` | **EXACT MATCH** |
| **Covariance Matrix ($\mathbf{\Sigma}$)** | Invariant baseline | Computed | `0.00e+00` | **EXACT MATCH** |
| **Correlation Matrix ($\mathbf{R}$)** | Invariant baseline | Computed | `0.00e+00` | **EXACT MATCH** |
| **Correlation Shifts ($\Delta \mathbf{R}$)** | Invariant baseline | Computed | `0.00e+00` | **EXACT MATCH** |
| **Portfolio Holdout Status** | `UNAVAILABLE` | `UNAVAILABLE` | Identical enum | **EXACT MATCH** |

*All genuine historical factors exhibit variance safely above $10^{-12}$ (FX return $\sigma \approx 4.88\text{e}-3$, borrowing diff $\sigma \approx 4.13\text{e}-1$, investment diff $\sigma \approx 2.40\text{e}-1$). All entries in `correlation_validity_mask` are `True`.*

---

## 5. Test Suite Verification & Execution Evidence

### Focused Suite (`tests/test_monte_carlo_phase_4_1_2_2_3_3.py`)
All 25 tests passed in 20.81s:

```
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_1_eur_usd_base_eur_quote_usd_quote_per_base PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_2_usd_eur_base_usd_quote_eur_quote_per_base PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_3_eur_usd_explicit_usd_per_eur_units PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_4_usd_eur_explicit_eur_per_usd_units PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_5_explicit_unit_contradicting_currencies_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_6_missing_base_or_quote_metadata_with_generic_quote_per_base_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_7_unsupported_currency_pair_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_8_identical_base_and_quote_currencies_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_9_raw_value_and_provenance_mismatch_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_10_boundary_date_mismatch_fails_closed PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamAStrictFXQuotationConsistency::test_11_canonical_fx_initialization_unchanged PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_1_exact_constant_calibration_factor PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_2_exact_constant_holdout_factor PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_3_near_constant_calibration_factor_below_threshold PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_4_near_constant_holdout_factor_below_threshold PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_5_nonzero_factor_variance_safely_above_threshold PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_6_pairwise_validity_masks PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_7_single_factor_zero_variance_behavior PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_8_no_global_warning_suppression PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamBNearZeroCorrelationSemantics::test_9_genuine_historical_correlation_values_unchanged PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamCResearchResultInvarianceEvidence::test_reconcile_initial_market_levels PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamCResearchResultInvarianceEvidence::test_reconcile_sample_counts PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamCResearchResultInvarianceEvidence::test_reconcile_covariance_and_correlation_matrices PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamCResearchResultInvarianceEvidence::test_reconcile_holdout_correlation_shifts PASSED
tests/test_monte_carlo_phase_4_1_2_2_3_3.py::TestWorkstreamCResearchResultInvarianceEvidence::test_reconcile_portfolio_holdout_status PASSED
```

### Full Repository Regression Run
```
======================= 485 passed in 115.79s (0:01:55) =======================
```
- Total test count: 485 passed.
- Regressions: 0.
- Ruff lint check: 0 errors across entire repository.

---

## 6. Preserved Research Boundaries & Non-Goals

1. **No Phase 5 Transition**: Phase 5 (Arbitrage & Glitch Detection) remains strictly unopened.
2. **No New Forecasting Models**: No predictive models, machine learning, or speculative estimators were introduced.
3. **Portfolio Holdout Invariance**: The portfolio holdout diagnostic remains unequivocally classified as `UNAVAILABLE` due to the lack of intraday point-in-time bid/ask execution quotes.
4. **Research Classifications Preserved**: Dataset remains classified under `SIMULATED_RESEARCH_PROXY` and `ESTIMATED_LAG`.
