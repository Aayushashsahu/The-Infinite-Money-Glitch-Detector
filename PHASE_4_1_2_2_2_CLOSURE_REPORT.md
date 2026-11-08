# Phase 4.1.2.2.2 — Canonical FX Panel Integrity & Research Artifact Reconciliation
## Final Engineering & Research Integrity Closure Report

**The Infinite Money Glitch Detector**  
**Core principle:** *Mathematics first. Data second. Prediction third. AI last.*  
**Status:** COMPLETE & INDEPENDENTLY REPRODUCIBLE  
**Data Classification:** `SIMULATED_RESEARCH_PROXY`  
**Point-in-Time Policy:** `ESTIMATED_LAG`  
**Portfolio Holdout Classification:** `UNAVAILABLE`  

---

## 1. Executive Summary & Engineering Baselines

Phase 4.1.2.2.2 completes the canonical FX normalization audit, sample counts reconciliation, convergence truthfulness reporting, and Federal Reserve unscheduled closure handling across the Monte Carlo simulation engine and research artifact pipeline.

### Engineering Baseline & Lineage

| Attribute | Phase 4.1.2.2.1 Predecessor | Phase 4.1.2.2.2 Current State |
|---|---|---|
| **Stage A Source Commit** | `2e7a0e28f11b6cb1e4d77051772648fb43c08182` | `f346131cb356881f44382a154c0323e55a476b68` |
| **Stage B Results Commit** | `6e7ab2b60cc3848ac877ff6a3895323a1ff3f979` | *Pending Stage B commit* |
| **Test Suite Baseline** | 391 passed (Python 3.11 & 3.12) | **412 passed** (21 new tests, 0 failures) |
| **Linter Status** | Ruff clean | **Ruff clean** (0 warnings, 0 errors) |
| **Research Classification** | `SIMULATED_RESEARCH_PROXY` | `SIMULATED_RESEARCH_PROXY` |
| **PIT Policy Mode** | `ESTIMATED_LAG` | `ESTIMATED_LAG` |
| **Portfolio Holdout Status** | `UNAVAILABLE` | `UNAVAILABLE` |
| **FX Factor Pipeline Quote** | Raw `EUR_per_USD` (unnormalized) | **Canonical `USD_per_EUR` throughout** |
| **Initial Spot vs Panel Quote** | Reciprocal discrepancy (1.0956 vs 0.9127) | **Strictly unified canonical `USD_per_EUR`** |
| **Sample Counts Accounting** | N vs N-1 ambiguous labeling | **Strict Level Dates ($N$) vs Transitions ($N-1$)** |
| **Checkpoint Stability Disclosure** | Broad claim of stability | **Honest per-model disclosure (5 pass, 1 fail)** |

All modifications strictly preserve historical phase results (`data/results/phase_4/`, `phase_4_1/`, `phase_4_1_1/`, `phase_4_1_2/`, `phase_4_1_2_1/`, `phase_4_1_2_2/`, `phase_4_1_2_2_1/`). No historical artifacts were modified or overwritten. All outputs are isolated in `data/results/phase_4_1_2_2_2/`.

---

## 2. Workstream A — Canonical FX Normalization Throughout Factor Pipeline

### Problem Solved
Prior to Phase 4.1.2.2.2, initial spot market level resolution utilized `_normalize_fx_quote_to_usd_per_eur(fx_obs)` (converting raw `EUR_per_USD` quotes ~0.91274 into canonical `USD_per_EUR` ~1.095602). However, `build_fx_carry_factor_panel()` appended raw source values (`fx_raw.append(fx_o.value)`) and computed log returns directly on raw values (`fx_returns = compute_log_returns(fx_raw)`). Consequently:
- Initial spot level and historical factor returns used reciprocal quote conventions.
- An appreciation of the euro (raw EUR/USD quote falling from 0.94 to 0.92) incorrectly manifested as negative log returns in the factor series.

### Implementation Details
1. **Canonical FX Normalization**: Updated `build_fx_carry_factor_panel()` to normalize every historical FX observation into canonical `USD_per_EUR` using `_normalize_fx_quote_to_usd_per_eur(fx_o)` before computing log returns:
   $$\text{canonical\_level}_t = \begin{cases} S_t & \text{if unit is } \text{USD\_per\_EUR} \\ \frac{1.0}{S_t} & \text{if unit is } \text{EUR\_per\_USD} \end{cases}$$
2. **Log Return Computation**: Log returns are calculated strictly on the canonical series:
   $$r_t = \ln\left(\frac{\text{canonical\_level}_t}{\text{canonical\_level}_{t-1}}\right)$$
   Euro appreciation now correctly and consistently produces positive factor returns across the factor panel and strategy simulation engine.
3. **Dual Preservation of Levels**: `FactorPanel` records both `raw_levels` (unaltered source values) and `canonical_levels` (normalized series), enabling complete auditability.
4. **Observation-Level Provenance**: Populated `FactorRowProvenance` with `raw_unit`, `normalized_level`, `pair`, `base_currency`, and `quote_currency`.
5. **Fail-Closed Validation**: Missing, empty, or ambiguous quote metadata strictly fails closed without heuristic magnitude guessing.

---

## 3. Workstream B — Audit of Factor Unit Normalizations

1. **Interest Rate Normalization**: Built `_normalize_rate_to_percentage_points(obs)` to standardize all rate observations:
   - `percent`: preserved directly as percentage points (e.g., $4.25\% \to 4.25$).
   - `decimal`: converted via $v \times 100$ (e.g., $0.0425 \to 4.25$).
   - `bps`: converted via $v / 100$ (e.g., $425.0 \to 4.25$).
   - Unrecognized or ambiguous rate units fail closed with `ValueError`.
2. **Basis Point Differencing**: Factor difference series use `compute_differences(rates_in_percentage_points) * 100`, accurately producing basis point changes ($\Delta \text{bps} = (r_t - r_{t-1}) \times 100$).
3. **ECB Borrowing & US Treasury Yields**: Validated ECB Main Refinancing Operations rate (`KR.MRR_FR.LEV`), US Treasury 1-Month Constant Maturity Yield (`DGS1MO`), and US Treasury 3-Month Yield (`DGS3MO`) across the calibration and holdout windows.

---

## 4. Workstream C — Checkpoint Stability Truthfulness

The platform reports finite-sample checkpoint stability honestly and refuses to mask convergence failures. Checkpoint stability assesses whether simulation distribution metrics remain within tight numerical tolerances when evaluated across sample checkpoints ($N \in \{500, 750, 1000\}$).

### Cross-Model Checkpoint Stability Breakdown ($N=1,000$, $\text{seed}=42$)

| Model Name | Checkpoint Stability Status | Loss Prob Shift ($\Delta$) | Tolerance | Notes |
|---|:---:|:---:|:---:|---|
| **Multivariate Gaussian** | `ACHIEVED` | 0.0120 | $\le 0.02$ | Mean, median, VaR, CVaR, prob(loss) stable |
| **Moving-Block Bootstrap (20d)** | `ACHIEVED` | 0.0080 | $\le 0.02$ | Mean, median, VaR, CVaR, prob(loss) stable |
| **IID Bootstrap** | `ACHIEVED` | 0.0140 | $\le 0.02$ | Mean, median, VaR, CVaR, prob(loss) stable |
| **Stationary Bootstrap (20d)** | `ACHIEVED` | 0.0110 | $\le 0.02$ | Mean, median, VaR, CVaR, prob(loss) stable |
| **Multivariate Student-t** | `ACHIEVED` | 0.0130 | $\le 0.02$ | Mean, median, VaR, CVaR, prob(loss) stable |
| **Regime-Conditioned Bootstrap** | `NOT_ACHIEVED` | **0.0390** | $> 0.02$ | **Loss probability shifted by 0.0390 (> 0.02)** |

**Key Finding**: Exactly **5 models achieved checkpoint stability** and **1 model failed** (`Regime-Conditioned Bootstrap`). The research report, simulation manifest, and model comparison artifact clearly document this failure.

> [!IMPORTANT]
> Finite-sample checkpoint stability across $N \in \{500, 750, 1000\}$ does not establish asymptotic convergence. Tail risk metrics (such as VaR 95% and CVaR 95%, with 50 tail observations) remain subject to finite-sample sampling variation.

---

## 5. Workstream D — Mathematical Sample Counts Reconciliation

### Mathematical Identity: $N$ Level Dates Generate $N - 1$ Transitions
A common source of confusion in quantitative finance reporting is conflating the number of daily price level observations ($N$) with the number of return/difference transitions ($N - 1$). Phase 4.1.2.2.2 rigorously reconciles all dates and sample counts across `FactorPanel`, `split_calibration_holdout`, and `CalibrationReport`:

$$\text{Transition Count} = \text{Aligned Level Count} - 1$$

### Reconciled Windows Breakdown

| Period | Window Dates | Aligned Level Dates ($N$) | Level Date Range | Transition Dates ($N-1$) | Transition Date Range |
|---|---|:---:|---|:---:|---|
| **Full Panel** | 2020-01-01 to 2024-12-31 | **1,237** | `2020-01-06` to `2024-12-31` | **1,236** | `2020-01-07` to `2024-12-31` |
| **Calibration** | 2020-01-01 to 2023-12-31 | **990** | `2020-01-06` to `2023-12-29` | **989** | `2020-01-07` to `2023-12-29` |
| **Holdout** | 2024-01-01 to 2024-12-31 | **248** | `2023-12-29` to `2024-12-31` | **247** | `2024-01-02` to `2024-12-31` |

### Slicing & Continuity Mechanics
To construct the first holdout return transition on `2024-01-02`, the holdout level series includes the final calibration level date (`2023-12-29`) as its baseline:
$$r_{\text{2024-01-02}} = \ln\left(\frac{S_{\text{2024-01-02}}}{S_{\text{2023-12-29}}}\right)$$
This prevents artificial data truncation while strictly avoiding look-ahead leakage.

---

## 6. Workstream E — Volatility Regime Thresholds Reconciliation

Volatility regime thresholds are dynamically calibrated from 63-day rolling annualized standard deviations of daily log returns over the in-sample calibration window:
- **Low Volatility Threshold (20th Percentile)**: **5.74%** annualized.
- **High Volatility Threshold (80th Percentile)**: **9.49%** annualized.

### 2024 Out-of-Sample Holdout Evaluation
- **Realized 2024 Annualized FX Volatility**: **6.18%**.
- **Regime Classification**: **`NORMAL_VOLATILITY`** ($5.74\% \le 6.18\% \le 9.49\%$).
- **Predictive Percentile**: Realized volatility falls in the 0.6th percentile of the unconditioned simulation distribution, reflecting the unusually suppressed volatility environment of 2024 compared to historical calibration dynamics (2020–2023).

---

## 7. Workstream F — Federal Reserve Board Historical Unscheduled Closures

The `FederalReserveH15Calendar` implementation now incorporates authoritative historical unscheduled closures and release timestamp overrides:

### Historical Unscheduled Closures Registered
1. **2018-12-05**: National Day of Mourning for President George H.W. Bush (Executive Order 13854).
2. **2012-10-29 & 2012-10-30**: Emergency Market & Federal Reserve Closure (Hurricane Sandy).
3. **2007-01-02**: National Day of Mourning for President Gerald R. Ford (Executive Order 13421).
4. **2004-06-11**: National Day of Mourning for President Ronald Reagan (Executive Order 13343).
5. **2001-09-11**: Emergency Closure (September 11 Terrorist Attacks).

### Hybrid Method Architecture
All calendar methods (`is_exceptional_closure`, `register_exceptional_closure`, `register_release_timestamp_override`, `get_h15_release_timestamp`, `is_fed_business_day`) are exposed via a `_HybridMethod` descriptor, enabling both class-level (`FederalReserveH15Calendar.is_exceptional_closure(d)`) and instance-level (`FED_H15_CALENDAR.is_exceptional_closure(d)`) invocation without API breakage.

---

## 8. Workstream G — Cross-Model Risk & Return Distribution ($N=1,000$, $H=252$)

Evaluated under `ESTIMATED_LAG` point-in-time policy with canonical initial spot $S_0 = 1.095602$, initial borrowing rate $r_b = 4.50\%$, and initial investment yield $r_i = 5.57\%$:

| Model Architecture | Median Return | Mean Return | Volatility | VaR (95%) | CVaR (95%) | Prob(Loss) | Prob(DD $\ge$ 10%) | Checkpoint Stability |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Multivariate Gaussian** | +1.75% | +1.98% | 4.01% | -4.53% | -5.97% | 31.9% ($\pm$1.47%) | 0.3% | `ACHIEVED` |
| **Moving-Block Bootstrap (20d)** | +2.25% | +2.23% | 4.01% | -4.41% | -5.93% | 27.9% ($\pm$1.42%) | 0.7% | `ACHIEVED` |
| **IID Bootstrap** | +1.99% | +2.01% | 3.99% | -4.25% | -6.26% | 32.1% ($\pm$1.48%) | 0.4% | `ACHIEVED` |
| **Stationary Bootstrap (20d)** | +2.06% | +2.00% | 3.97% | -4.41% | -5.82% | 31.0% ($\pm$1.46%) | 0.3% | `ACHIEVED` |
| **Multivariate Student-t** | +1.60% | +1.88% | 3.68% | -3.77% | -6.38% | 29.2% ($\pm$1.44%) | 0.8% | `ACHIEVED` |
| **Regime-Conditioned Bootstrap** | +1.71% | +1.60% | 3.93% | -5.21% | -6.98% | 34.1% ($\pm$1.50%) | 1.5% | `NOT_ACHIEVED` |

---

## 9. Workstream H — Generated Research Artifacts & Integrity Manifest

All 18 research artifacts were successfully generated and verified in `data/results/phase_4_1_2_2_2/`:

| Artifact File | Description | SHA-256 Digest |
|---|---|---|
| `availability_audit.json` | Comprehensive Point-in-Time Availability Audit | `d9c40f48fc47fb3346719491281d8eecb88a1647e14904fd75498f262ecbe065` |
| `calibration_report.json` | Calibration Sample Statistics & Level/Transition Reconciliation | `a8994f4d70c6e5ecccd230fe91e41882f0a409da5fe33ef816dc1954ab6e3060` |
| `factor_panel_manifest.json` | Factor Panel Metadata & Row-Level Audit Provenance | `f15aa918aff4a4dd11d65f4b90c487cbfb8ee5b64a307948f15df7ded873befe` |
| `gaussian_results.json` | Multivariate Gaussian Simulation Distribution | `d0f183890f37528566043c0b3d5498b59386df40cefa5977a36368af24f7ba85` |
| `bootstrap_results.json` | Moving-Block Bootstrap Simulation Distribution | `c8f794780f5e1c555b7ab0ae83ff3df7880698afe4058cb73fdea77cd8b7e54a` |
| `student_t_results.json` | Multivariate Student-t Simulation Distribution | `b8b0f10f0f5d93d7c1cd9696d2b4dd4808cb70956e386da41a09d5a183cdad0f` |
| `regime_results.json` | Regime-Conditioned Bootstrap Simulation Distribution | `1a7fb588d8b800ebbd86ad2bc71b53cab58410d4319f4793bc286f0d0bcda348` |
| `model_comparison.json` | 6-Model Risk/Return Summary & Checkpoint Stability | `5cc589f97423e8666aaa6434182b802dc8e918cc323d74502fe0982314aa4ea4` |
| `stress_test_results.json` | 19 Deterministic Macro-Financial Stress Scenarios | `4053f6596b8bb9aaa03373acca584fc60ebaf964e414b62acbfb4d343fe56348` |
| `correlation_stress_comparison.json` | Paired CRN Empirical vs Decoupled Correlation Test | `f1ec34a7a82db91f4b416b8eb5afe00a22e4af199c3b45cbb373c7ff1a5caf84` |
| `factor_holdout_diagnostics.json` | Out-of-Sample 2024 Factor Realization Diagnostics | `27f4d47747432a23db77e5a66708c86262d0f69d7b7c6b9a6d21a3823a9f2645` |
| `portfolio_holdout_diagnostics.json` | Portfolio Out-of-Sample Status (`UNAVAILABLE`) | `0082f477222570c9ab5402f94e5d3f8c6d11bd04502106350e82d5378060be2d` |
| `holdout_diagnostics.json` | Consolidated Holdout Evaluation | `822c9f4c772eec411cdd4a513f81228324e2f388a9f0a20513fdd11d4a9c5ef5` |
| `calendar_validation.json` | Settlement & Release Calendar Validation Report | `bf3c68d8f64c98aa6363ba7b176d891f99e18d21cab8e58af3067b982a8b4ff0` |
| `funding_sensitivity.json` | Fixed vs Floating Borrowing Funding Sensitivity | `c85e8812a1bb0939ff187b49e7e063f49d0e19d22833ce3030e1ec4f0563d9d1` |
| `convergence_report.json` | Checkpoint Convergence Diagnostics Across Models | `bf14c44a7885afc26e5277de170890b0b1be8a4c74bd1763e7b58b8b7da7c614` |
| `phase_4_1_2_2_2_research_report.md` | Comprehensive Analytical Research Markdown Report | `363a1daa6759ddf6bffd44c68e3d1a9d1f5d01f31f8e60f124e80c1248eb3aef` |
| `simulation_manifest.json` | Complete Environment & Hardware Provenance Manifest | `e1c9cb9fcb635017f2820e49ce987cb782799f1a503f3d52e3dfd1717c93645d` |

---

## 10. Verification and Test Results

The test suite was executed across the complete repository with zero regressions:
```
================= 412 passed, 7 warnings in 67.88s (0:01:07) ==================
```
- **New Test Suite**: `tests/test_monte_carlo_phase_4_1_2_2_2.py` (21 passed).
- **Existing Tests**: 391 passed (100% regression free).
- **Linter**: `ruff check .` passed with 0 errors.

---

## 11. Remaining Limitations & Boundaries

1. **Portfolio Holdout**: Remains classified as `UNAVAILABLE` because no genuine historical executable execution record exists for this strategy. The platform explicitly prohibits manufacturing synthetic fills to fabricate an out-of-sample portfolio test.
2. **Phase 5 Not Started**: Phase 5 (live execution integrations, production brokers, execution algorithms) has **not** begun. No new strategy features or optimization loops were introduced.
3. **Finite-Sample Uncertainty**: Checkpoint stability at $N=1,000$ does not imply asymptotic convergence. Tail estimates at 95% confidence rely on 50 observations in the lowest 5% quantile and remain subject to statistical sampling error.
