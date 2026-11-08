# Phase 4.1.2.2.3 — Holdout Forecast Initialization & Scenario-Date Integrity Closure
## Final Engineering & Research Integrity Closure Report

**The Infinite Money Glitch Detector**  
**Core principle:** *Mathematics first. Data second. Prediction third. AI last.*  
**Status:** COMPLETE & INDEPENDENTLY REPRODUCIBLE  
**Data Classification:** `SIMULATED_RESEARCH_PROXY`  
**Point-in-Time Policy:** `ESTIMATED_LAG`  
**Portfolio Holdout Classification:** `UNAVAILABLE`  

---

## 1. Executive Summary & Engineering Baselines

Phase 4.1.2.2.3 resolves the critical defect in the holdout predictive-path construction in `examples/run_monte_carlo_research.py`. Previously, holdout predictive paths were generated using `horizon = len(holdout_panel.dates)` (247 dates) while passing `dates = holdout_panel.dates`. Because the scenario path sampler reconstructs $H + 1$ levels (248 levels), the scenario path contained 248 price levels but only 247 calendar dates. This length mismatch violated `ScenarioPath` calendar validation (`validate_calendar_dates`). Furthermore, path generation omitted explicit initial FX, borrowing, and investment rates, causing the sampler to fall back to arbitrary default parameters (`1.09`, `0.04`, `0.05`) instead of anchoring at the true in-sample calibration-boundary state.

### Engineering Baseline & Lineage

| Attribute | Phase 4.1.2.2.2 Predecessor | Phase 4.1.2.2.3 Current State |
|---|---|---|
| **Stage A Source Commit** | `f346131cb356881f44382a154c0323e55a476b68` | `790e1e1bae8b3e9ead0300cfc80abd897d89a746` |
| **Stage B Results Commit** | `25941d76e3ad3b91cde012b84b9197209fbad133` | `PENDING_STAGE_B_COMMIT` |
| **Test Suite Baseline** | 412 passed (Python 3.11 & 3.12) | **424 passed** (12 new tests, 0 failures) |
| **Linter Status** | Ruff clean | **Ruff clean** (0 warnings, 0 errors) |
| **Research Classification** | `SIMULATED_RESEARCH_PROXY` | `SIMULATED_RESEARCH_PROXY` |
| **PIT Policy Mode** | `ESTIMATED_LAG` | `ESTIMATED_LAG` |
| **Portfolio Holdout Status** | `UNAVAILABLE` | `UNAVAILABLE` |
| **Holdout Scenario Levels** | 248 levels, 247 dates (length mismatch) | **248 levels, 248 dates (strictly synchronized)** |
| **Holdout Initial State Anchoring** | Fallback defaults (`1.09`, `0.04`, `0.05`) | **True Calibration Boundary State (`2023-12-29`)** |
| **Holdout Initial Spot ($S_0$)** | Fallback `1.09` USD/EUR | **Canonical `1.104997` USD/EUR** |
| **Holdout Initial Borrowing Rate ($r_b$)** | Fallback `0.04` (4.00%) | **Boundary `0.0450` (4.50%)** |
| **Holdout Initial Investment Yield ($r_i$)** | Fallback `0.05` (5.00%) | **Boundary `0.0555` (5.55%)** |
| **First Holdout Step Modeling** | Undefined initial transition | **Step models `2023-12-29` to `2024-01-02`** |
| **Calendar Validation** | Failed on holdout path length mismatch | **PASSED for `JOINT_TARGET2_FED` & `WEEKDAY_TRADING_PROXY`** |

All modifications strictly preserve historical phase results (`data/results/phase_4/` through `phase_4_1_2_2_2/`). No historical artifacts were modified or overwritten. All outputs are isolated in `data/results/phase_4_1_2_2_3/`.

---

## 2. Workstream A — Holdout Predictive-Path Construction & Calendar Alignment

### Problem Solved
In `examples/run_monte_carlo_research.py`, predictive paths were formerly initialized via:
```python
predictive_paths = mb_model.generate_paths(
    num_paths=1000,
    horizon=len(holdout_panel.dates),
    dates=holdout_panel.dates,
)
```
This exhibited two fundamental defects:
1. **Length Mismatch**: `holdout_panel.dates` comprises 247 transition dates (`2024-01-02` to `2024-12-31`). However, `generate_paths(horizon=247)` generates $H + 1 = 248$ levels (index 0 for $S_0$, indices 1..247 for transitions). Consequently, `len(p.dates) == 247 != len(p.fx_rates) == 248`. Any downstream strategy execution or calendar validator checking `validate_calendar_dates(p.dates, len(p.fx_rates))` failed with:
   ```
   ValueError: Scenario path calendar dates length mismatch: received 247 dates, expected exactly 248.
   ```
2. **Omission of Boundary State**: `generate_paths()` defaulted to `initial_fx = 1.09`, `initial_borrowing_rate = 0.04`, and `initial_investment_rate = 0.05`. These hardcoded defaults did not reflect the true historical economic boundary state on `2023-12-29` ($S_0 \approx 1.104997$, $r_b = 4.50\%$, $r_i = 5.55\%$).

### Implementation: `generate_holdout_predictive_paths`
We implemented `generate_holdout_predictive_paths()` in `src/simulation/monte_carlo/holdout.py`:
1. **Date Alignment**:
   - Uses `holdout_panel.level_dates` (length 248), spanning `2023-12-29` to `2024-12-31`.
   - Sets `horizon = len(holdout_panel.dates)` (247 steps), so generated paths have $H + 1 = 248$ levels matching the 248 dates.
   - Enforces fallback logic: if `level_dates` is empty, safely prepends `calibration_panel.dates[-1]` (`2023-12-29`).
2. **Calibration Boundary State Anchoring**:
   - `initial_fx = float(calibration_panel.canonical_levels["FX_EUR_USD_LOGRET"][-1])` ($1.1049967955$ USD per EUR).
   - `initial_borrowing_rate = float(calibration_panel.canonical_levels["RATE_DIFF_EUR_BORROW_BPS"][-1]) / 100.0` ($0.0450$ decimal annual rate).
   - `initial_investment_rate = float(calibration_panel.canonical_levels["YIELD_DIFF_USD_1M_BPS"][-1]) / 100.0` ($0.0555$ decimal annual rate).
3. **Transition Dynamics**:
   - Index 0 corresponds to calibration close on `2023-12-29`.
   - Index 1 corresponds to holdout open on `2024-01-02`.
   - The first path innovation correctly models the economic transition across the New Year boundary:
     $$r_1 = \ln\left(\frac{S_{\text{2024-01-02}}}{S_{\text{2023-12-29}}}\right)$$
4. **Strict Post-Condition Assertions**:
   - `len(dates) == len(fx_rates) == len(borrowing_rates) == len(investment_rates) == horizon + 1 == 248`.
   - `dates[0] == date(2023, 12, 29)`.
   - `abs(fx_rates[0] - initial_fx) < 1e-9`.
   - `abs(borrowing_rates[0] - initial_borrow) < 1e-9`.
   - `abs(investment_rates[0] - initial_invest) < 1e-9`.
   - `validate_calendar_dates(dates, 248, "JOINT_TARGET2_FED")` passes.

---

## 3. Workstream B — Empirical Invariance & Factor Holdout Diagnostics

### Empirical Invariance of Return Metrics
Because factor holdout diagnostics evaluate log returns:
$$r_t = \ln\left(\frac{S_t}{S_{t-1}}\right) = \ln\left(\frac{S_0 \cdot \exp(\sum_{i=1}^t \Delta r_i)}{S_0 \cdot \exp(\sum_{i=1}^{t-1} \Delta r_i)}\right) = \Delta r_t$$
and drawdown ratios:
$$\text{DD}_t = \frac{S_t}{\max_{\tau \le t} S_\tau} - 1 = \frac{S_0 \cdot X_t}{\max_{\tau \le t} (S_0 \cdot X_\tau)} - 1 = \frac{X_t}{\max_{\tau \le t} X_\tau} - 1$$
the empirical return and drawdown percentages are mathematically invariant ($< 10^{-14}$) to the choice of initial spot level $S_0$. However, grounding $S_0$ at the true calibration boundary ($1.104997$) and aligning the 248 dates is required for economic realism, strategy cash-flow valuation, interest accrual calculations, and strict calendar compliance.

### 2024 Factor Realization Summary
- **Holdout Window**: 247 transition trading days (`2024-01-02` to `2024-12-31`).
- **Actual Realized Cumulative FX Return**: **-5.98%** (EUR depreciated against USD).
- **Actual Realized Annualized FX Volatility**: **6.18%**.
- **Actual Realized Maximum Drawdown**: **-7.21%**.
- **Volatility Regime Classification**: **`NORMAL_VOLATILITY`** ($5.74\% \le 6.18\% \le 9.49\%$).
- **Predictive Percentiles**:
  - Cumulative Return: **22.9%** percentile (within central 95% predictive band $[-14.95\%, +14.84\%]$).
  - Volatility: **0.6%** percentile (reflects unusually low 2024 realized volatility).
  - Max Drawdown: **64.9%** percentile (well within predictive distribution, median $-8.41\%$).
- **KS Test**: Kolmogorov-Smirnov descriptive statistic $D = 0.0940$ ($p = 0.0559$).

### Portfolio Holdout Status
`PortfolioHoldoutDiagnostics` reports:
- **Status**: **`UNAVAILABLE`**
- **Reason**: No genuine historical executable portfolio series exists for the 2024 holdout. The strategy remains classified as `SIMULATED_RESEARCH_PROXY` without live execution evidence.
- **Rule Enforced**: The platform strictly prohibits fabricating synthetic broker fills or imputing order fills from factor data.

---

## 4. Workstream C — Checkpoint Stability & Cross-Model Risk Breakdown

All 6 simulation models were executed with $N = 1,000$ paths and $H = 252$ steps under `ESTIMATED_LAG` PIT policy:

### Cross-Model Risk & Return Distribution ($N=1,000$, $H=252$, $\text{seed}=42$)

| Model Architecture | Median Return | Mean Return | Volatility | VaR (95%) | CVaR (95%) | Prob(Loss) | Prob(DD $\ge$ 10%) | Checkpoint Stability |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Multivariate Gaussian** | +1.75% | +1.98% | 4.01% | -4.53% | -5.97% | 31.9% ($\pm$1.47%) | 0.3% | `ACHIEVED` |
| **Moving-Block Bootstrap (20d)** | +2.25% | +2.23% | 4.01% | -4.41% | -5.93% | 27.9% ($\pm$1.42%) | 0.7% | `ACHIEVED` |
| **IID Bootstrap** | +1.99% | +2.01% | 3.99% | -4.25% | -6.26% | 32.1% ($\pm$1.48%) | 0.4% | `ACHIEVED` |
| **Stationary Bootstrap (20d)** | +2.06% | +2.00% | 3.97% | -4.41% | -5.82% | 31.0% ($\pm$1.46%) | 0.3% | `ACHIEVED` |
| **Multivariate Student-t** | +1.60% | +1.88% | 3.68% | -3.77% | -6.38% | 29.2% ($\pm$1.44%) | 0.8% | `ACHIEVED` |
| **Regime-Conditioned Bootstrap** | +1.71% | +1.60% | 3.93% | -5.21% | -6.98% | 34.1% ($\pm$1.50%) | 1.5% | `NOT_ACHIEVED` |

**Checkpoint Stability Truthfulness**: Exactly 5 models achieved finite-sample stability at $N=1,000$. The Regime-Conditioned Bootstrap model honestly reports `CHECKPOINT_STABILITY_NOT_ACHIEVED` because its loss probability shifted by 0.0390 between checkpoints, exceeding the 0.02 threshold.

---

## 5. Workstream D — Generated Research Artifacts & Integrity Manifest

All 18 research artifacts were generated and verified in `data/results/phase_4_1_2_2_3/`:

| Artifact File | Description | SHA-256 Digest |
|---|---|---|
| `availability_audit.json` | Comprehensive Point-in-Time Availability Audit | `d9c40f48fc47fb3346719491281d8eecb88a1647e14904fd75498f262ecbe065` |
| `calibration_report.json` | Calibration Sample Statistics & Level/Transition Reconciliation | `a8994f4d70c6e5ecccd230fe91e41882f0a409da5fe33ef816dc1954ab6e3060` |
| `factor_panel_manifest.json` | Factor Panel Metadata & Row-Level Audit Provenance | `f15aa918aff4a4dd11d65f4b90c487cbfb8ee5b64a307948f15df7ded873befe` |
| `gaussian_results.json` | Multivariate Gaussian Simulation Distribution | `c342d16015f4e66dde68d2f77e2d7a8338826c232af122a526547c85dc90bb34` |
| `bootstrap_results.json` | Moving-Block Bootstrap Simulation Distribution | `2f95dcf80ec095a1e39d2424e28c6598d5b71d2f10fbf9733b1e46bbd27d1eee` |
| `student_t_results.json` | Multivariate Student-t Simulation Distribution | `cc06de387576f71beecfc9f800cb2487b8bc06610074087ab34ae68413736bab` |
| `regime_results.json` | Regime-Conditioned Bootstrap Simulation Distribution | `a239aa72bc32470966c7ba566bc7718389dd641b63ce0396b9e5c7f4caa394d3` |
| `model_comparison.json` | 6-Model Risk/Return Summary & Checkpoint Stability | `5cc589f97423e8666aaa6434182b802dc8e918cc323d74502fe0982314aa4ea4` |
| `stress_test_results.json` | 19 Deterministic Macro-Financial Stress Scenarios | `4053f6596b8bb9aaa03373acca584fc60ebaf964e414b62acbfb4d343fe56348` |
| `correlation_stress_comparison.json` | Paired CRN Empirical vs Decoupled Correlation Test | `f1ec34a7a82db91f4b416b8eb5afe00a22e4af199c3b45cbb373c7ff1a5caf84` |
| `factor_holdout_diagnostics.json` | Out-of-Sample 2024 Factor Realization Diagnostics | `0e2b5fa1e7ddd3de28ebe997e4d9dcfc138356fc077a5d461770fbd96a9d143e` |
| `portfolio_holdout_diagnostics.json` | Portfolio Out-of-Sample Status (`UNAVAILABLE`) | `0082f477222570c9ab5402f94e5d3f8c6d11bd04502106350e82d5378060be2d` |
| `holdout_diagnostics.json` | Consolidated Holdout Evaluation | `822c9f4c772eec411cdd4a513f81228324e2f388a9f0a20513fdd11d4a9c5ef5` |
| `calendar_validation.json` | Settlement & Release Calendar Validation Report | `bf3c68d8f64c98aa6363ba7b176d891f99e18d21cab8e58af3067b982a8b4ff0` |
| `funding_sensitivity.json` | Fixed vs Floating Borrowing Funding Sensitivity | `c85e8812a1bb0939ff187b49e7e063f49d0e19d22833ce3030e1ec4f0563d9d1` |
| `convergence_report.json` | Checkpoint Convergence Diagnostics Across Models | `bf14c44a7885afc26e5277de170890b0b1be8a4c74bd1763e7b58b8b7da7c614` |
| `phase_4_1_2_2_3_research_report.md` | Comprehensive Analytical Research Markdown Report | `c3081f21b13951a0e087bbcf5756453159f3fd221a4f4ad94fb7cf001f2a7c96` |
| `simulation_manifest.json` | Complete Environment & Hardware Provenance Manifest | `74c951a3c43d20860433dba0b584cfa796f4b8620cc66ffa71ba70adaefe25ca` |

---

## 6. Verification and Test Results

The full test suite was executed across the complete repository with zero failures and zero regressions:
```
================= 424 passed, 9 warnings in 75.70s (0:01:15) ==================
```
- **New Test Suite**: `tests/test_monte_carlo_phase_4_1_2_2_3.py` (12 passed).
- **Existing Test Suites**: 412 passed (100% regression-free).
- **Linter**: `ruff check .` passed with 0 errors.

---

## 7. Remaining Boundaries & Research Protocol

1. **Portfolio Holdout**: Remains classified as `UNAVAILABLE`. No live executions, broker fills, or order-book executions occurred during 2024. The strategy remains classified as `SIMULATED_RESEARCH_PROXY`.
2. **Phase 5 Not Started**: Phase 5 (live execution integrations, production brokers, execution algorithms) has **not** begun. No new strategy features or optimization loops were introduced.
3. **Finite-Sample Uncertainty**: Checkpoint stability at $N=1,000$ does not imply asymptotic convergence. Tail estimates at 95% confidence rely on 50 observations in the lowest 5% quantile and remain subject to statistical sampling error.
