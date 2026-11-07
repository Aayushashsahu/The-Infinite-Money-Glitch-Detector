# Phase 4.1.2 — Final Research Integrity & Reproducibility Closure Report

**Project**: The Infinite Money Glitch Detector  
**Status**: Complete, Reconciled & Formally Validated  
**Baseline Stage A Commit**: `a498cfca8aa726630260fe948b0e6bb9e5d31e68`  
**Test Suite**: 344 tests passing on Python 3.11 and Python 3.12 (0 failed, 0 skipped)  
**Historical Calibration Window**: `2020-01-01` to `2023-12-31` (991 aligned trading days)  
**Holdout Evaluation Window**: `2024-01-01` to `2024-12-31` (247 aligned trading days)  
**Data Classification**: `SIMULATED_RESEARCH_PROXY`  
**Guiding Principle**: *Mathematics first. Data second. Prediction third. AI last.*  

---

## Executive Summary

Phase 4.1.2 completes the final quantitative integrity, calendar mechanics, point-in-time (PIT) availability, reporting consistency, and reproducibility closure for the Monte Carlo & Market Scenario Laboratory. 

All previous historical research artifacts in `data/results/phase_4/`, `data/results/phase_4_1/`, and `data/results/phase_4_1_1/` remain strictly preserved as immutable baselines. The authoritative Phase 4.1.2 outputs are located in:
`data/results/phase_4_1_2/`

The implementation strictly followed a two-stage commit execution model:
1. **Stage A — Source Snapshot**: All source code modifications, helper algorithms, and the comprehensive 13-test Phase 4.1.2 test suite were committed as `a498cfca8aa726630260fe948b0e6bb9e5d31e68` (`feat(simulation): Phase 4.1.2 source implementation and test suite`), ensuring a clean working tree.
2. **Stage B — Generated Research Outputs**: The research runner was executed directly against the Stage A snapshot (`1,000` paths, `252` steps, seed `42`), generating all 16 machine-readable artifacts, this closure report, and updated documentation (`docs(simulation): Phase 4.1.2 research outputs and closure report`).

---

## 1. Key Closed Deficiencies

### 1.1 CI Artifact Hash Integrity & LF Line Ending Normalization
- **Issue**: GitHub Actions CI failed with SHA-256 mismatches between recorded manifest digests and computed hashes due to platform line-ending differences (Windows CRLF `\r\n` vs. Linux LF `\n`).
- **Correction**:
  - Enforced `* text eol=lf` in `.gitattributes` for all repository JSON, Markdown, and Python files.
  - Standardized `export_json` and `export_markdown` to write in binary mode (`"wb"`) with explicit `\n` line endings.
  - Recomputed and validated digests from the exact bytes present in committed files.
  - Eliminated all silent `pytest.skip` calls on missing or unverified artifacts across all test suites.

### 1.2 Explicit Point-in-Time Availability Semantics
- **Issue**: Ambiguity regarding when macro-financial observations become available to strategy decision algorithms.
- **Correction**:
  - Implemented `get_session_decision_timestamp(session_date, decision_time_utc=time(16, 0))` representing the 16:00 UTC (17:00 CET) European market rebalance cutoff.
  - Implemented `get_effective_availability_timestamp(obs)` enforcing documented release schedules:
    - Same-day EUR/USD reference rates published at ~16:00 CET are available at 17:00 CET / 16:00 UTC.
    - US Treasury yields (DGS1MO, DGS3MO) published by FRED are subject to next-business-day reporting lag at 15:00 UTC (Monday yield available Tuesday 15:00 UTC; Friday yield available Monday 15:00 UTC).
    - ECB policy rates (DFR, Main Refinancing Operations) are bound by effective policy timestamps.
  - Implemented `is_observation_available_as_of(obs, as_of, strict_executable)` preventing future observation date/timestamp look-ahead and excluding retrospective data under strict executable mode.
  - Implemented `resolve_observation_as_of(observations, as_of)` selecting the authoritative revision available as of decision time and blocking revisions published after the cutoff.

### 1.3 Genuinely Measured Calendar Validation Evidence
- **Issue**: Previous calendar validation reports contained static or assumed booleans rather than empirical measurements.
- **Correction**:
  - Completely rewrote `validate_market_calendar_evidence()` to execute real simulated trading sessions and assert:
    - $t=0$ initial market state exhibits exactly zero interest earned and zero realized P&L.
    - Friday-to-Monday session transition generates exactly 3 elapsed calendar days (`weekend_elapsed_days == 3`).
    - Joint TARGET2/Fed Easter holiday closure generates exactly 5 elapsed calendar days (`holiday_elapsed_days == 5`).
    - 30-calendar-day contractual tenor maturity exit step occurs on the first trading session where $\text{sessions}[t] \ge \text{entry} + 30\text{d}$ and $\text{sessions}[t-1] < \text{entry} + 30\text{d}$.
    - Independent numerical compound financing formula matches the execution engine within $10^{-5}$ tolerance.
    - Exact dimension alignment: $N$ transitions and $N+1$ levels across all rate and price arrays.

### 1.4 Holdout Drawdown Mathematical Consistency
- **Issue**: In computing maximum drawdown across the 2024 holdout window, peak tracking initialized at $\exp(r_0)$, omitting drawdowns initiated on the very first trading day.
- **Correction**:
  - Standardized factor and portfolio holdout diagnostics by prepending starting wealth `1.0`:
    $$\text{cum\_wealth} = [1.0, e^{r_0}, e^{r_0 + r_1}, \dots]$$
  - Peak is initialized at `1.0`, ensuring any initial negative return accurately reflects drawdown from starting wealth.

### 1.5 EUR/USD Quote-Direction & Carry-Trade Translation Economics
- **Issue**: Ambiguity in reporting currency appreciation semantics.
- **Correction**:
  - Explicitly verified that EUR/USD is quoted as USD per 1 EUR (e.g. 1.10 USD/EUR).
  - An increase in EUR/USD represents **EUR appreciation** and **USD depreciation**.
  - In a carry trade borrowing EUR to invest in USD, EUR appreciation causes an FX translation loss upon reconverting depreciated USD to repay the EUR liability.
  - Documented canonical rate normalization: units of borrowing currency A (EUR) per unit of investment currency B (USD) equals $1 / S_{\text{EUR/USD}}$.

### 1.6 Correlation Stress Test Semantics & Monte Carlo Uncertainty
- **Issue**: Previous comparisons lacked uncertainty quantification for loss probabilities and clear attribution semantics.
- **Correction**:
  - Framed zero off-diagonal correlation ($R = I$) strictly as a hypothetical stress condition with Common Random Numbers (CRN).
  - Defined all attribution differences unambiguously as $\Delta = \text{Stressed} - \text{Baseline}$.
  - Added paired standard error estimation:
    $$SE(\Delta \text{ProbLoss}) = \frac{\text{std}((r_{\text{stressed}} < 0) - (r_{\text{base}} < 0))}{\sqrt{N}}$$
  - Added `prob_loss_difference_se` to `CorrelationStressComparison`.

---

## 2. Six-Model Comparative Risk and Return Distribution Matrix

Generated from `1,000` simulation paths across `252` trading day steps ($N=1,000$, seed $42$):

| Simulation Model | Paths | Median Return | Mean Return | Ann. Vol | VaR (95%) | CVaR (95%) | Prob(Loss) [SE] | Prob(Drawdown >= 10%) | Mean Pure FX | Mean Financing |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Multivariate Gaussian** | `1,000` | `+1.47%` | `+1.49%` | `3.36%` | `-4.06%` | `-5.15%` | `33.9%` (±1.50%) | `0.1%` | `-0.10%` | `-1.63%` |
| **Moving-Block Bootstrap (20d)** | `1,000` | `+1.36%` | `+1.38%` | `3.35%` | `-3.78%` | `-5.04%` | `35.8%` (±1.52%) | `0.1%` | `-0.22%` | `-1.64%` |
| **IID Bootstrap** | `1,000` | `+1.69%` | `+1.73%` | `3.34%` | `-3.74%` | `-5.01%` | `31.7%` (±1.47%) | `0.0%` | `+0.13%` | `-1.62%` |
| **Stationary Bootstrap (20d)** | `1,000` | `+1.37%` | `+1.44%` | `3.33%` | `-4.03%` | `-5.07%` | `34.1%` (±1.50%) | `0.0%` | `-0.15%` | `-1.63%` |
| **Multivariate Student-t** | `1,000` | `+1.37%` | `+1.58%` | `3.06%` | `-3.51%` | `-5.28%` | `31.4%` (±1.47%) | `0.6%` | `-0.01%` | `-1.63%` |
| **Regime-Conditioned Bootstrap** | `1,000` | `+1.81%` | `+1.79%` | `3.29%` | `-3.93%` | `-5.05%` | `30.6%` (±1.46%) | `0.1%` | `+0.13%` | `-1.64%` |

---

## 3. Real 2024 Out-of-Sample Holdout Diagnostics

### Factor-Level Holdout Evaluation (Pure FX EUR/USD)
- **Holdout Window**: `2024-01-02` to `2024-12-31` (`247` aligned trading days).
- **Predictive Evaluation Sample**: `1,000` simulated factor paths.
- **Realized 2024 FX Volatility**: `6.18%` (categorized as `HIGH_VOLATILITY` / Normal regime).
- **Predictive Volatility Median**: `7.94%` (Realized Volatility Percentile: `0.5%`).
- **Realized 2024 Cumulative FX Return**: `+6.36%` (EUR appreciated vs USD).
- **Predictive FX Return Percentile**: `75.3%` (Monte Carlo SE: `±1.36%`).
- **95% Predictive Interval for FX Return**: `[-13.29%, +17.82%]`.
- **Realized Max Drawdown**: `-5.04%` (Predictive Drawdown Percentile: `85.0%`).
- **Two-Sample Kolmogorov-Smirnov Test**: Statistic = `0.0937`, p-value = `0.0577` (reported descriptively; unadjusted for serial dependence).

### Strategy Portfolio Holdout Evaluation
- **Status**: `UNAVAILABLE`
- **Data Classification**: `SIMULATED_RESEARCH_PROXY`
- **Audit Findings**:
  - No genuine executable broker accounts or order-book fills existed during 2024.
  - The strategy portfolio return is not conflated with raw factor returns.
  - Portfolio predictive coverage is explicitly marked `UNAVAILABLE` to eliminate false validation claims.

---

## 4. Point-in-Time Availability & Provenance Audit

- **Total Database Records Inspected**: `8,908`
- **Synthetic Records Excluded**: `8`
- **Genuine Historical Records Evaluated**: `8,900`
- **Date Window Exclusions (outside 2020-2023 calibration)**: `1,910`
- **Alignment Exclusions (incomplete cross-factor coverage)**: `1,044`
- **Exhaustive Reconciliation Status**: `EXACT (100% Reconciled, 0 residual)`

| Evidence Classification Category | Observation Count | Percentage | Point-in-Time Status |
| :--- | :---: | :---: | :--- |
| Exact Timestamp Verified | `0` | `0.00%` | Strict Order-Book Verified |
| Estimated Release Schedule | `8,724` | `98.02%` | Estimated Lag Policy Applied |
| Retrospective Availability | `176` | `1.98%` | Research Proxy Only |
| Missing Availability Evidence | `0` | `0.00%` | Conservative Zero-Weight |
| Unrecognized Evidence | `0` | `0.00%` | Excluded |
| **Total Genuine Observations** | **`8,900`** | **100.00%** | **Reconciliation Residual: 0** |

---

## 5. Artifact Directory & Cryptographic Digest Audit

All 16 research artifacts plus manifest in `data/results/phase_4_1_2/` are validated with exact cryptographic SHA-256 digests:

| Artifact File | Description | SHA-256 Digest |
| :--- | :--- | :--- |
| `availability_audit.json` | 5-bucket PIT availability reconciliation audit | `064e733962ce50f56a9cea70580494eca305501a1ab33296877c3f9a16e45dd9` |
| `factor_holdout_diagnostics.json` | Out-of-sample 2024 FX factor diagnostics | `2b9b889c22c5e85bfaabfba43b8b566b551fc5ebd4a1a74845980487695e6333` |
| `portfolio_holdout_diagnostics.json` | UNAVAILABLE strategy portfolio holdout classification | `0082f477222570c9ab5402f94e5d3f8c6d11bd04502106350e82d5378060be2d` |
| `correlation_stress_comparison.json` | Common Random Numbers correlation breakdown study | `29c6524e42ee457267115e698fa94d02c7eab21079d21b97d56e23e4faede432` |
| `calendar_validation.json` | Genuinely measured trading calendar mechanics | `bf3c68d8f64c98aa6363ba7b176d891f99e18d21cab8e58af3067b982a8b4ff0` |
| `funding_sensitivity.json` | Fixed vs floating funding rate shock sensitivity | `13a9f64c81b4dbd6d14001fb23ee6ebfa1b4d18f937b4caa9ddfbaee087f448b` |
| `model_comparison.json` | Cross-model risk/return comparison table (6 models) | `bdc59d41b148e3578c10e6ce6bb7d233f3ad828f05c77379bd7fff5890ee474d` |
| `convergence_report.json` | Multi-metric Monte Carlo convergence diagnostics | `dc2ab51962a907c413378e586664c81ea6e565f83cfc04fafefa266533405be4` |
| `phase_4_1_2_research_report.md` | Authoritative generated Markdown research report | `0f72b89d4efbe96884e16a5c82d637c8f8029e409a16deda69bc20907c2d2cee` |
| `calibration_report.json` | Calibration factor summary and stationarity metrics | `add06b4faa72ddd69ba99958f978417f9d52b23c17249a35f57e129027af3268` |
| `factor_panel_manifest.json` | Full 2020-2024 factor panel specification | `8fe05106600ed35b2a23839307a81f4ccd62dccfcb9980817d363545fcc22b54` |
| `gaussian_results.json` | Multivariate Gaussian Monte Carlo results (1,000 paths) | `3b385ef78b2d08514073bed46df2e5e1e3feba3a6f07313e7409c96c0d8d0d85` |
| `bootstrap_results.json` | Moving-Block Bootstrap results (1,000 paths) | `73c63d55eaf536ab7294cbe0e6c66158347bd041652f1335d2ac3d3229492ce4` |
| `student_t_results.json` | Multivariate Student-t results (1,000 paths) | `41a28930e60037868bf59609a13d9ff95ce0035dadf82c3afc91d0721bca0814` |
| `regime_results.json` | Regime-Conditioned Bootstrap results (1,000 paths) | `0fdf2d10485ee3fce5b9d2ad3ec2bdc77ab5116c212e387ed241fcf2489f6be2` |
| `stress_test_results.json` | Deterministic macro-financial stress test suite | `97557bf9e6a61cccae4f56ddd7db2e68e96230117d50b0a72599fe9137491af4` |
| `holdout_diagnostics.json` | Legacy combined holdout diagnostic format | `f142650635fcb7d1ce3e804b0013377159a41fcf18c5c97a23fc998f50cfede0` |
| `simulation_manifest.json` | Environmental provenance & reproducibility manifest | Recorded in manifest metadata |

---

## 6. Reproducibility & Verification Commands

To reproduce the full research run from source:
```bash
# 1. Run complete test suite (344 tests passing)
uv run pytest

# 2. Re-run Phase 4.1.2 simulation study (1,000 paths, 252 steps, seed 42)
uv run python examples/run_monte_carlo_research.py --output-dir data/results/phase_4_1_2 --paths 1000 --horizon 252 --seed 42

# 3. Verify cryptographic hash and manifest completeness
uv run pytest tests/test_monte_carlo_phase_4_1_2.py
```

**Status**: Phase 4.1.2 is formally closed. All requirements have been fulfilled with mathematical rigor and reproducible evidence.
