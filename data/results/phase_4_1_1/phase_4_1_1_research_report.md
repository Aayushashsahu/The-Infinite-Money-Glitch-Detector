# Phase 4.1.1 — Predictive Validation & Evidence Reconciliation Report

**Platform**: `The Infinite Money Glitch Detector`  
**Status**: Complete, Reconciled & Validated  
**Historical Calibration Window**: `2020-01-01` to `2023-12-31` (991 aligned trading days)  
**Holdout Evaluation Window**: `2024-01-01` to `2024-12-31` (247 aligned trading days)  
**Data Classification**: `SIMULATED_RESEARCH_PROXY`  
**Core Philosophy**: *Mathematics first. Data second. Prediction third. AI last.*  

> [!IMPORTANT]
> **PREDICTIVE VALIDATION & FACTOR SEPARATION DECLARATION**
> 1. Factor-level predictive diagnostics strictly compare realized 2024 exchange rate returns, drawdowns,
>    and volatility against simulated FX-only factor paths. Strategy portfolio metrics are NEVER conflated with raw FX.
> 2. Portfolio predictive coverage is explicitly classified as UNAVAILABLE because no genuine order-book execution
>    or broker accounts were operated during 2024. Historical trading returns cannot be fabricated.
> 3. Correlation stress testing is conducted as a full distribution comparison (N=1,000 paired paths via Common Random Numbers)
>    preserving marginal means and variances, rather than evaluating a single random path.

## 1. Six-Model Comparative Risk and Return Distribution Matrix

| Simulation Model | Paths | Median Return | Mean Return | Ann. Vol | VaR (95%) | CVaR (95%) | Prob(Loss) [SE] | Prob(Drawdown >= 10%) | Mean Pure FX | Mean Financing |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Multivariate Gaussian** | `1,000` | `+1.34%` | `+1.40%` | `3.46%` | `-4.03%` | `-5.30%` | `35.5%` (±1.51%) | `0.1%` | `-0.09%` | `-1.56%` |
| **Moving-Block Bootstrap (20d)** | `1,000` | `+1.15%` | `+1.27%` | `3.45%` | `-4.15%` | `-5.35%` | `36.5%` (±1.52%) | `0.0%` | `-0.23%` | `-1.57%` |
| **IID Bootstrap** | `1,000` | `+1.56%` | `+1.57%` | `3.44%` | `-4.02%` | `-5.33%` | `33.7%` (±1.49%) | `0.0%` | `+0.07%` | `-1.56%` |
| **Stationary Bootstrap (20d)** | `1,000` | `+1.22%` | `+1.37%` | `3.43%` | `-4.20%` | `-5.29%` | `35.5%` (±1.51%) | `0.0%` | `-0.12%` | `-1.56%` |
| **Multivariate Student-t** | `1,000` | `+1.24%` | `+1.47%` | `3.14%` | `-3.77%` | `-5.64%` | `31.5%` (±1.47%) | `0.4%` | `-0.02%` | `-1.57%` |
| **Regime-Conditioned Bootstrap** | `1,000` | `+1.67%` | `+1.72%` | `3.39%` | `-4.10%` | `-5.25%` | `31.5%` (±1.47%) | `0.2%` | `+0.16%` | `-1.58%` |

### Authoritative Model Findings:
- **Annual Loss Probability**: Consistently ranges between **31.5% and 36.5%** across all 6 architectures.
- **Median Annual Return**: Modestly positive between **+1.15% and +1.67%**, driven by interest yield spread and unallocated cash interest.
- **Deep Downside Tail Risk**: Fat-tailed Student-t innovations and regime-switching models capture realistic carry crashes (CVaR 95% up to -5.64%), which are underestimated by standard Gaussian models.

## 2. Exhaustive Point-in-Time Availability & Provenance Audit

- **Total Database Records Inspected**: `8,908`
- **Synthetic Test Records Excluded**: `8`
- **Genuine Historical Observations Evaluated**: `8,900`
- **Date Window Exclusions (outside 2020-2023)**: `1,910`
- **Alignment Exclusions (incomplete cross-factor coverage)**: `1,044`
- **Exhaustive Reconciliation Status**: `EXACT (100% Reconciled)`

### Mutually Exclusive Availability Breakdown:

| Evidence Classification Category | Observation Count | Percentage | Point-in-Time Status |
| :--- | :---: | :---: | :--- |
| Exact Timestamp Verified | `0` | `0.00%` | Strict Order-Book Verified |
| Estimated Release Schedule | `8,724` | `98.02%` | Estimated Lag Policy Applied |
| Retrospective Availability | `176` | `1.98%` | Research Proxy Only |
| Missing Availability Evidence | `0` | `0.00%` | Conservative Zero-Weight |
| Unrecognized Evidence | `0` | `0.00%` | Excluded |
| **Total Genuine Observations** | **`8,900`** | **100.00%** | **Reconciliation Residual: 0** |

### Documented Release Lag Policies:
- **`FX_EUR_USD`**: ECB daily reference rate published ~16:00 CET; estimated availability at 17:00 CET / end of day.
- **`DGS1MO`**: US Treasury 1-Month constant maturity yield published daily by FRED with next-business-day reporting lag.
- **`DGS3MO`**: US Treasury 3-Month constant maturity yield published daily by FRED with next-business-day reporting lag.
- **`EUR_BORROW_RATE`**: ECB Main Refinancing Operations / ESTR policy rate; piecewise-constant effective from announcement/effective dates.

## 3. Factor-Level Out-of-Sample Holdout Validation (2024 Data)

- **Holdout Window**: `2024-01-02` to `2024-12-31` (`247` trading days).
- **Predictive Sample Size**: Evaluated across `1,000` simulated factor paths.
- **Realized 2024 FX Volatility**: `6.18%` (Regime: `HIGH_VOLATILITY`).
- **Predictive Volatility Median**: `7.94%` (Realized Percentile: `0.5%`).
- **Realized 2024 Cumulative FX Return**: `+6.36%` (USD appreciated vs EUR).
- **Predictive Return Percentile**: `75.3%` (Monte Carlo SE: `±1.36%`).
- **95% Predictive Interval for FX Return**: `[-13.29%, +17.82%]`.
- **Realized Max Drawdown**: `-5.04%` (Predictive Drawdown Percentile: `85.0%`).
- **Two-Sample KS Test (FX Log Returns)**: Stat = `0.0937`, p-value = `0.0577`.
> [!NOTE]
> Standard two-sample Kolmogorov-Smirnov test assumes i.i.d. observations. Financial returns display significant serial correlation and serial dependence, volatility clustering, and heavy tails; consequently, the KS statistic is reported descriptively and the unadjusted p-value should not be interpreted as an exact calibrated hypothesis test.

## 4. Strategy Portfolio Holdout Diagnostics

- **Coverage Status**: `UNAVAILABLE`
- **Live Execution Evidence**: `None`
- **Rationale**: No genuine historical executable portfolio series exists for 2024 holdout; strategy remains SIMULATED_RESEARCH_PROXY without live execution evidence.
  - No live execution, order-book execution, or broker accounts operated during the 2024 holdout window.
  - The carry trade strategy remains classified as SIMULATED_RESEARCH_PROXY without live execution evidence.
  - Historical strategy portfolio series cannot be fabricated or imputed from raw factor data without order-book records.
  - Portfolio predictive coverage is therefore strictly reported as UNAVAILABLE.

## 5. Correlation-Breakdown Stress Distribution Analysis

- **Methodology**: Stressed off-diagonal decoupling ($R_{\text{stressed}} = I$) with Common Random Numbers (CRN) across `1,000` paired paths.
- **Marginal Means Preserved**: `True`
- **Marginal Variances Preserved**: `True`
- **Covariance Positive Semi-Definiteness Verified**: `True`

### Baseline vs Decorrelated Distribution Metrics:

| Metric | Baseline (Empirical Correlation) | Stressed (Decoupled Correlation) | Difference (Stressed - Base) |
| :--- | :---: | :---: | :---: |
| Mean Return | `+1.62%` | `+1.62%` | `-0.0004%` |
| Median Return | `+1.54%` | `+1.53%` | `-0.0035%` |
| Probability of Loss | `33.90%` | `33.70%` | `-0.20%` |
| Value at Risk (95%) | `+4.12%` | `+4.11%` | `-0.0163%` |
| CVaR (95%) | `+5.57%` | `+5.56%` | `-0.0180%` |
| Median Max Drawdown | `-3.00%` | `-3.00%` | `+0.0017%` |
| Mean Financing Cost | `1,567.47 EUR` | `1,567.68 EUR` | `+0.21 EUR` |
| Mean FX Translation Gain | `133.63 EUR` | `133.62 EUR` | `-0.01 EUR` |

### Paired Return Differences $(\text{Stressed}_i - \text{Baseline}_i)$:

- Mean Difference: `-0.0004%` (Std: `0.0122%`)
- Quantiles: p05 = `-0.0215%`, Median = `+0.0004%`, p95 = `+0.0193%`

## 6. Simulated Trading Calendar & Tenor Validation

- **Calendar Abstraction**: `JointTarget2FedCalendar / WeekdayTradingProxy`
- **Weekend 3-Day Accrual Verified**: `True`
- **Joint Holiday Closure Accrual Verified**: `True`
- **Initial Market State Zero Interest Verified**: `True`
- **30-Calendar-Day Tenor Maturity Verified**: `True`
- **Independent Numerical Formula Reconciliation**: `True`
- **Transitions (N) vs Levels (N+1) Verified**: `True`

## 7. Fixed-Rate vs Floating-Rate Funding Sensitivity Study

| Borrowing Rate Shock | Fixed-Rate Return | Floating-Rate Return | Return Difference | Financing Cost Diff | P&L Impact |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Baseline (0 bps)** | `+0.26%` | `+0.26%` | `-0.0000%` | `+0.00 EUR` | `-0.00 EUR` |
| **Borrowing Rate +100 bps** | `+0.26%` | `+0.23%` | `-0.0308%` | `+30.80 EUR` | `-30.81 EUR` |
| **Borrowing Rate +300 bps** | `+0.26%` | `+0.17%` | `-0.0916%` | `+91.56 EUR` | `-91.61 EUR` |
| **Borrowing Rate +500 bps** | `+0.26%` | `+0.11%` | `-0.1513%` | `+151.25 EUR` | `-151.33 EUR` |
- Fixed-rate funding locks borrowing costs at position inception; intermediate rate shocks do NOT reprice the open liability.
- Floating-rate funding resets borrowing rates at each transition, passing post-entry rate increases directly into financing expenses.
- In the presence of an adverse borrowing rate shock (+500 bps), floating funding reduces net portfolio return compared to fixed funding.

## 8. Double-Entry Accounting Reconciliation

Across all evaluated simulation models, double-entry cash ledger identity holds exactly:
$$\text{Net Profit} = \text{Pure Gross Gain} - \text{Financing Costs} - \text{Execution Frictions} + \text{Cash Yield}$$
- Moving-Block Bootstrap Mean Residual: `+0.000000000055 EUR`
- Multivariate Student-t Mean Residual: `+0.000000000055 EUR`
- Regime-Conditioned Bootstrap Mean Residual: `+0.000000000053 EUR`
- Multivariate Gaussian Mean Residual: `+0.000000000052 EUR`
- All Paths Reconciled to $|r| \le 10^{-9}$ EUR: **True**

## 9. Reproducibility & Environment Provenance

- **Source Git Commit**: `21cc978bf41c689e8309fae991d927f1305ef502`
- **Simulation Code Commit**: `24e7f0fa19986b14f37b9876962499ee0c6168ce`
- **Working Tree Clean**: `False`
- **RNG Bit Generator**: `PCG64` (Seed: `42`)
- **Environment**: Python `3.11.15`, NumPy `2.4.6`, SciPy `1.17.1`