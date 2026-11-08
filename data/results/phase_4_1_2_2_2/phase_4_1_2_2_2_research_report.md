# Phase 4.1.2.2.2 — Canonical FX Panel Integrity & Research Artifact Reconciliation Report

**Platform**: `The Infinite Money Glitch Detector`  
**Status**: Complete, Reconciled & Validated  
**Historical Calibration Window**: `2020-01-01` to `2023-12-31` (990 aligned level dates [2020-01-06 to 2023-12-29], 989 factor return transitions [2020-01-07 to 2023-12-29])  
**Holdout Evaluation Window**: `2024-01-02` to `2024-12-31` (248 aligned level dates [2023-12-29 to 2024-12-31], 247 factor return transitions [2024-01-02 to 2024-12-31])  
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

> [!IMPORTANT]
> **ECONOMIC INSTRUMENT & DATA-SOURCE SEMANTICS DECLARATION**
> 1. **ECB Reference Rates as Statistical Proxies**: The FX rate series uses ECB euro foreign exchange reference rates (mirrored by Frankfurter).
>    These rates are indicative fixing averages for reference purposes, not executable two-way institutional market quotes.
> 2. **US Treasury Yields vs Commercial Deposit Rates**: US Treasury yields (DGS1MO) represent sovereign default-free yields.
>    They are not commercial bank deposit or money market fund rates, which would incur custodial fees, credit spreads, and regulatory cash drag.
> 3. **Policy Rates vs Institutional Borrowing Rates**: ECB policy rates (e.g. KR.MRR_FR.LEV / DFR) represent central bank policy targets,
>    not unsecured or secured commercial bank borrowing costs available to an arbitrageur, which require interbank credit spreads,
>    haircuts, and broker margin financing markups.

## 1. Six-Model Comparative Risk and Return Distribution Matrix

| Simulation Model | Paths | Median Return | Mean Return | Ann. Vol | VaR (95%) | CVaR (95%) | Prob(Loss) [SE] | Prob(Drawdown >= 10%) | Mean Pure FX | Mean Financing |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Multivariate Gaussian** | `1,000` | `+1.75%` | `+1.98%` | `4.01%` | `-4.53%` | `-5.97%` | `31.9%` (±1.47%) | `0.3%` | `+0.33%` | `-2.53%` |
| **Moving-Block Bootstrap (20d)** | `1,000` | `+2.25%` | `+2.23%` | `4.01%` | `-4.41%` | `-5.93%` | `27.9%` (±1.42%) | `0.7%` | `+0.58%` | `-2.55%` |
| **IID Bootstrap** | `1,000` | `+1.99%` | `+2.01%` | `3.99%` | `-4.25%` | `-6.26%` | `32.1%` (±1.48%) | `0.4%` | `+0.38%` | `-2.54%` |
| **Stationary Bootstrap (20d)** | `1,000` | `+2.06%` | `+2.00%` | `3.97%` | `-4.41%` | `-5.82%` | `31.0%` (±1.46%) | `0.3%` | `+0.36%` | `-2.54%` |
| **Multivariate Student-t** | `1,000` | `+1.60%` | `+1.88%` | `3.68%` | `-3.77%` | `-6.38%` | `29.2%` (±1.44%) | `0.8%` | `+0.23%` | `-2.53%` |
| **Regime-Conditioned Bootstrap** | `1,000` | `+1.71%` | `+1.60%` | `3.93%` | `-5.21%` | `-6.98%` | `34.1%` (±1.50%) | `1.5%` | `-0.13%` | `-2.55%` |

### Per-Model Checkpoint Stability Convergence Breakdown:
| Simulation Model | Checkpoint Stability Status | Mean Return | Median Return | Loss Probability | VaR (95%) | CVaR (95%) | Max Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Multivariate Gaussian** | `CHECKPOINT_STABILITY_ACHIEVED` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` |
| **Moving-Block Bootstrap (20d)** | `CHECKPOINT_STABILITY_ACHIEVED` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` |
| **IID Bootstrap** | `CHECKPOINT_STABILITY_ACHIEVED` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` |
| **Stationary Bootstrap (20d)** | `CHECKPOINT_STABILITY_ACHIEVED` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` |
| **Multivariate Student-t** | `CHECKPOINT_STABILITY_ACHIEVED` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` |
| **Regime-Conditioned Bootstrap** | `CHECKPOINT_STABILITY_NOT_ACHIEVED` | `PASS` | `PASS` | `FAIL` | `PASS` | `PASS` | `PASS` |

### Authoritative Model Findings:
- **Annual Loss Probability**: Consistently ranges between **27.9% and 34.1%** across all 6 architectures.
- **Median Annual Return**: Modestly positive between **+1.60% and +2.25%**, driven by interest yield spread and unallocated cash interest.
- **Deep Downside Tail Risk**: Fat-tailed Student-t innovations and regime-switching models capture realistic carry crashes (worst CVaR 95% is -6.98%), which are underestimated by standard Gaussian models.

## 2. Exhaustive Point-in-Time Availability & Provenance Audit

- **Total Database Records Inspected**: `8,908`
- **Synthetic Test Records Excluded**: `8`
- **Genuine Historical Observations Evaluated**: `8,900`
- **Date Window Exclusions (outside 2020-2023)**: `1,910`
- **Alignment Exclusions (incomplete cross-factor coverage)**: `1,056`
- **Point-in-Time Mode Enforced**: `ESTIMATED_LAG`
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
- **`FX_EUR_USD`**: ECB daily reference rate published ~16:00 CET / ~15:00-16:00 UTC on observation date; available for decision at 16:00 UTC.
- **`DGS1MO`**: Federal Reserve H.15 Selected Interest Rates release published at 4:15 PM Eastern Time on next Federal Reserve business day (accounting for EST/EDT daylight saving and Federal Reserve holidays).
- **`DGS3MO`**: Federal Reserve H.15 Selected Interest Rates release published at 4:15 PM Eastern Time on next Federal Reserve business day (accounting for EST/EDT daylight saving and Federal Reserve holidays).
- **`EUR_BORROW_RATE`**: ECB Main Refinancing Operations / Deposit Facility Rate; piecewise-constant effective from 00:00 UTC on announcement/effective date.

> [!NOTE]
> **Data Source Accounting**: The historical database contains 8,900 genuine observations across all macroeconomic indicators (including annual World Bank inflation and GDP series). Out of these, 5,613 observations belong to the 4 evaluated daily financial factor series (EUR/USD, ECB policy rate, US Treasury 1M yield, and US Treasury 3M yield) that form the synchronized multi-factor panel.

### Initial Simulation Market State Grounding:

- **As-of Decision Timestamp**: `2024-01-02T16:00:00+00:00`
- **Initial FX Mid Rate**: `1.095602 USD/EUR` (from `frankfurter` `EUR/USD` on `2024-01-02`, raw=`0.91274`)
- **Initial Borrowing Rate**: `0.0450 (4.50%)` (from `ecb` `KR.MRR_FR.LEV` on `2024-01-02`)
- **Initial Investment Yield**: `0.0557 (5.57%)` (from `us_treasury` `DGS1MO` on `2023-12-28`)
- **Initial Net Yield Spread**: `+107.0 bps`
  - Grounded initial FX rate: 1.095602 USD/EUR from frankfurter EUR/USD on 2024-01-02 (raw=0.91274, unit=EUR_per_USD).
  - Grounded initial borrowing rate: 0.0450 (4.50%) from ecb KR.MRR_FR.LEV on 2024-01-02 (unit=percent).
  - Grounded initial investment rate: 0.0557 (5.57%) from us_treasury DGS1MO on 2023-12-28 (unit=percent).
  - Resolved strictly point-in-time as of 2024-01-02T16:00:00+00:00 under policy ESTIMATED_LAG.

## 3. Factor-Level Out-of-Sample Holdout Validation (2024 Data)

- **Holdout Window**: `2024-01-02` to `2024-12-31` (`247` trading days).
- **Predictive Sample Size**: Evaluated across `1,000` simulated factor paths.
- **Realized 2024 FX Volatility**: `6.18%` (Regime: `NORMAL_VOLATILITY`).
- **Predictive Volatility Median**: `7.95%` (Realized Percentile: `0.6%`).
- **Realized 2024 Cumulative FX Return**: `-5.98%` (EUR appreciated vs USD; provider quote EUR/USD rises when EUR strengthens against USD).
- **Predictive Return Percentile**: `22.9%` (Monte Carlo SE: `±1.33%`).
- **95% Predictive Interval for FX Return**: `[-14.95%, +14.84%]`.
- **Realized Max Drawdown**: `-7.21%` (Predictive Drawdown Percentile: `64.9%`).
- **Two-Sample KS Test (FX Log Returns)**: Stat = `0.0940`, p-value = `0.0559`.
> [!NOTE]
> Standard two-sample Kolmogorov-Smirnov test assumes i.i.d. observations. Financial returns display significant serial correlation and serial dependence, volatility clustering, and heavy tails; consequently, the KS statistic is reported descriptively and the unadjusted p-value should not be interpreted as an exact calibrated hypothesis test.

> [!NOTE]
> **Volatility Regime Horizons & Reconciliation**: Volatility regime thresholds are estimated from the distribution of rolling 63-trading-day annualized volatilities across the 2020–2023 calibration sample (warm-up excluded): Low Volatility (< 5.74%, lower 20th percentile), Normal Volatility (5.74% to 9.49%, central 20th–80th percentile band), and Stress Volatility (>= 9.49%, upper 20th percentile tail). Realized 2024 volatility (6.18%) represents full-year 247-trading-day sample annualized volatility, classified in the `NORMAL_VOLATILITY` regime. Predictive volatility percentile measures the empirical CDF position of realized 2024 volatility within the model's simulated out-of-sample distribution.

## 4. Strategy Portfolio Holdout Diagnostics

- **Coverage Status**: `UNAVAILABLE`
- **Live Execution Evidence**: `None`
- **Rationale**: No genuine historical executable portfolio series exists for 2024 holdout; strategy remains SIMULATED_RESEARCH_PROXY without live execution evidence.
  - No live execution, order-book execution, or broker accounts operated during the 2024 holdout window.
  - The carry trade strategy remains classified as SIMULATED_RESEARCH_PROXY without live execution evidence.
  - Historical strategy portfolio series cannot be fabricated or imputed from raw factor data without order-book records.
  - Portfolio predictive coverage is therefore strictly reported as UNAVAILABLE.

> [!NOTE]
> **Factor-Level vs Strategy-Level Holdout**: Factor holdout diagnostics evaluate whether simulated underlying market factors encompass realized 2024 economic moves. In contrast, strategy portfolio holdout requires genuine executable broker orders and fills, which did not operate in 2024. Therefore, strategy portfolio status is strictly UNAVAILABLE, and the strategy remains classified as SIMULATED_RESEARCH_PROXY.

## 5. Correlation-Breakdown Stress Distribution Analysis

- **Methodology**: Stressed off-diagonal decoupling ($R_{\text{stressed}} = I$) with Common Random Numbers (CRN) across `1,000` paired paths.
- **Marginal Means Preserved**: `True`
- **Marginal Variances Preserved**: `True`
- **Covariance Positive Semi-Definiteness Verified**: `True`

### Baseline vs Decorrelated Distribution Metrics:

| Metric | Baseline (Empirical Correlation) | Stressed (Decoupled Correlation) | Difference (Stressed - Base) |
| :--- | :---: | :---: | :---: |
| Mean Return | `+1.95%` | `+1.95%` | `+0.0007%` |
| Median Return | `+1.87%` | `+1.87%` | `+0.0051%` |
| Probability of Loss | `34.50%` | `34.60%` | `+0.10% (SE: ±0.10%)` |
| Value at Risk (95%) | `+4.61%` | `+4.62%` | `+0.0110%` |
| CVaR (95%) | `+6.28%` | `+6.31%` | `+0.0230%` |
| Median Max Drawdown | `-3.56%` | `-3.56%` | `-0.0009%` |
| Mean Financing Cost | `2,296.75 EUR` | `2,296.30 EUR` | `-0.45 EUR` |
| Mean FX Translation Gain | `355.71 EUR` | `355.72 EUR` | `+0.01 EUR` |

### Paired Return Differences $(\text{Stressed}_i - \text{Baseline}_i)$:

- Mean Difference: `+0.0007%` (Std: `0.0155%`)
- Quantiles: p05 = `-0.0239%`, Median = `-0.0002%`, p95 = `+0.0278%`

> [!NOTE]
> **Correlation Stress Framework & VaR Convention**: Value at Risk (95%) and Conditional VaR (95%) are reported as **positive loss magnitudes** relative to initial equity (e.g. VaR 95% of +2.50% represents a loss of 2.50% of capital at 95% confidence, corresponding to a return quantile of -2.50%). Paired return differences are defined as $\Delta_i = \text{Stressed}_i - \text{Baseline}_i$. Zero off-diagonal correlation ($R = I$) is a hypothetical stress condition, not an empirically observed historical state. Small observed sensitivity under this specific calibration must not be generalized to claim that correlation risk is unimportant in other market regimes.

## 6. Simulated Trading Calendar & Tenor Validation

- **Calendar Abstraction**: `JointTarget2FedCalendar`
- **Weekend 3-Day Accrual Verified**: `True`
- **Joint Holiday Closure Accrual Verified**: `True`
- **Initial Market State Zero Interest Verified**: `True`
- **30-Calendar-Day Tenor Maturity Verified**: `True`
- **Independent Numerical Formula Reconciliation**: `True`
- **Transitions (N) vs Levels (N+1) Verified**: `True`

## 7. Fixed-Rate vs Floating-Rate Funding Sensitivity Study

| Borrowing Rate Shock | Fixed-Rate Return | Floating-Rate Return | Return Difference | Financing Cost Diff | P&L Impact |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Baseline (0 bps)** | `+0.29%` | `+0.29%` | `+0.0000%` | `+0.00 EUR` | `+0.00 EUR` |
| **Borrowing Rate +100 bps** | `+0.27%` | `+0.24%` | `-0.0308%` | `+30.78 EUR` | `-30.82 EUR` |
| **Borrowing Rate +300 bps** | `+0.23%` | `+0.14%` | `-0.0916%` | `+91.48 EUR` | `-91.59 EUR` |
| **Borrowing Rate +500 bps** | `+0.20%` | `+0.05%` | `-0.1512%` | `+151.07 EUR` | `-151.24 EUR` |
- Fixed-rate funding locks borrowing costs at position inception; intermediate rate shocks do NOT reprice the open liability.
- Floating-rate funding resets borrowing rates at each transition, passing post-entry rate increases directly into financing expenses.
- In the presence of an adverse borrowing rate shock (+500 bps), floating funding reduces net portfolio return compared to fixed funding.

## 8. Double-Entry Accounting Reconciliation

Across all evaluated simulation models, double-entry cash ledger identity holds exactly:
$$\text{Net Profit} = \text{Pure Gross Gain} - \text{Financing Costs} - \text{Execution Frictions} + \text{Cash Yield}$$
- Moving-Block Bootstrap Mean Residual: `+0.000000000056 EUR`
- Multivariate Student-t Mean Residual: `+0.000000000058 EUR`
- Regime-Conditioned Bootstrap Mean Residual: `+0.000000000059 EUR`
- Multivariate Gaussian Mean Residual: `+0.000000000057 EUR`
- All Paths Reconciled to $|r| \le 10^{-9}$ EUR: **True**

## 9. Convergence & Checkpoint Stability Tracking

- **Stability Classification**: `CHECKPOINT_STABILITY` (evaluated across sequential path sample checkpoints).
- **Finite Sample Limitation**: At N=1,000 paths, exactly 50 observations fall below the 5th percentile tail (VaR 95%), which provides limited statistical precision for CVaR (Expected Shortfall) estimation.
- **Status**: Metric stability across checkpoints confirms finite-sample simulation stability, but does not establish asymptotic mathematical convergence.

## 10. Reproducibility & Environment Provenance

- **Source Git Commit**: `f346131cb356881f44382a154c0323e55a476b68`
- **Simulation Code Commit**: `f346131cb356881f44382a154c0323e55a476b68`
- **Working Tree Clean**: `False`
- **RNG Bit Generator**: `PCG64` (Seed: `42`)
- **Environment**: Python `3.11.15`, NumPy `2.4.6`, SciPy `1.17.1`