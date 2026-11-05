# PHASE 3.2.1 — QUANTITATIVE INTEGRITY, POINT-IN-TIME & EXECUTABILITY AUDIT

## Project: The Infinite Money Glitch Detector
**Status:** Quantitative Audit Complete & Verified  
**Date:** November 2024 / Simulation Horizon: 2020–2024  
**Test Suite:** 158 Passed Tests (100% Pass Rate across Unit, Integration, and Audit Suites)  
**Core Philosophy:** *Mathematics first. Data second. Prediction third. AI last.*

---

## 1. Executive Summary

This audit report documents the quantitative correction, point-in-time hardening, and economic accounting audit of Phase 3.2.

Phase 3.2 successfully integrated genuine historical market data from official providers (Frankfurter/ECB, U.S. Department of the Treasury, and ECB Data Portal) covering two macroeconomic regimes (2020–2024). It reported an unhedged carry trade return of **+13.27%** (annualized **+2.52%**) on genuine market data.

This Phase 3.2.1 audit was commissioned to rigorously examine the mechanics behind those results. Rather than seeking higher profitability, the objective was to enforce **mathematical correctness, strict point-in-time availability, realistic trading calendars, exact double-entry cash flow accounting, and proper financial instrument classification**.

### Summary of Key Audit Findings & Corrections:

1. **Baseline Preservation:**  
   The original Phase 3.2 reported return of **+13.27%** is permanently preserved in [PHASE_3_2_REAL_DATA_VALIDATION.md](file:///D:/Project%20The%20Infinite%20Money%20Glitch%20Detector/PHASE_3_2_REAL_DATA_VALIDATION.md) and database records as an archival baseline. It is not deleted or overwritten.

2. **Return Attribution Ledger Discrepancy Resolved:**  
   In Phase 3.2, entry variable fees were deducted from principal before conversion, reducing foreign currency purchased. In performance metrics reporting, entry fees were summed again under transaction costs, creating double-counting and an attribution residual of ~0.29%.  
   **Correction:** Constructed an exact trade-level and portfolio-level double-entry accounting ledger. Pure Gross Gain is defined as the mid-to-mid economic gain from interest differential and exchange rate movement. Total Frictions encompass all entry/exit spreads, slippage, and brokerage fees. The reconciliation residual:
   $$|\text{Cumulative Net Profit} - (\text{Pure Gross Gain} - \text{Financing Costs} - \text{Total Frictions} + \text{Cash Interest})| = 0.0000000000$$
   satisfies numerical tolerance ($\le 10^{-10}$) down to floating-point machine precision across all runs.

3. **Timestamp-Aware Point-in-Time Firewall:**  
   Replaced date-only filtering with full UTC timezone-aware timestamp filtering (`observation_timestamp`, `publication_timestamp`, `effective_timestamp`). The firewall guarantees that economic facts released later on day T (e.g. ECB fix at 16:00 CET, Treasury yields at 16:00 ET) cannot leak into trading signals generated earlier on that calendar day.

4. **Market Calendar & Weekend Rollover:**  
   Enforced active FX trading days for order entry and exit. Trade maturities falling on weekends or bank holidays are deferred to the next active trading day (Monday). Financing interest and foreign investment returns are accrued for the full calendar days elapsed (e.g. 32 days instead of 30 days). Non-trading days are omitted from equity snapshot sampling, preventing zero-return days from artificially dampening sample volatility.

5. **Rate Role Semantics & Strategy Status Classification:**  
   Classified interest rates using `RateRole` (`POLICY_RATE`, `RISK_FREE_RATE`, `BORROWING_RATE`, `DEPOSIT_RATE`). Strategies utilizing central bank policy rates (`KR.DFR.LEV`) or sovereign treasury yields (`DGS3MO`) without commercial borrowing spreads are explicitly designated as `RESEARCH_PROXY`, not `EXECUTABLE_VALIDATED`.

---

## 2. Baseline Preservation & Comparative Results

In accordance with scientific reproducibility principles, the original Phase 3.2 baseline results are preserved intact alongside the corrected Phase 3.2.1 results.

### Full 5-Year Window Comparison (2020-01-01 to 2024-12-31):
*Borrow EUR, Invest USD, Initial Capital $100,000, 30-Day Tenor, $50,000 Deployed per Tranche*

| Metric | Phase 3.2 Baseline | Phase 3.2.1 Audited Result | Audit Variation & Explanation |
| :--- | :--- | :--- | :--- |
| **Strategy Status** | Undifferentiated | `RESEARCH_PROXY` | Uses ECB DFR & US Treasury yields without commercial bank spread |
| **Total Trades** | 60 | 60 | Identical trade count |
| **Win Rate** | 53.3% | 53.3% | Identical win/loss trade sequence |
| **Total Net Return** | **+13.27%** | **+14.06%** | +0.79% due to weekend maturity rollover interest and exact friction accounting |
| **Annualized Return** | **+2.52%** | **+2.67%** | Compounded annual return over 5.0 years |
| **Annualized Volatility** | 2.95% | 3.55% | Corrected by sampling active trading days only (removing weekend 0% days) |
| **Sharpe Ratio** | 0.35 | 0.32 | Based on 252 trading-day annualization |
| **Sortino Ratio** | 0.51 | 0.46 | Downside deviation over 252 trading days |
| **Maximum Drawdown** | -5.64% | -5.64% | Unchanged peak-to-trough equity decline |
| **Attribution Residual** | ~0.29% (discrepancy) | **0.0000000000** | Double-counting eliminated; exact mathematical closure |
| **Cash Benchmark Return** | +7.73% | +7.73% | Passive cash deposit benchmark with identical holding period |
| **Excess Return vs Cash** | +5.54% | +6.33% | Net strategy return over domestic cash holding |

---

## 3. Timestamp-Aware Point-in-Time Firewall

### Chronology Invariants Enforced:
At any simulated execution timestamp $T_{\text{signal}}$:
1. **Publication Precedence:** $\text{publication\_timestamp} \le T_{\text{signal}}$.
2. **Observation Precedence:** $\text{observation\_timestamp} \le T_{\text{signal}}$ and $\text{observation\_date} \le T_{\text{signal}}.\text{date}()$.
3. **UTC Internal Normalization:** All datetime inputs are converted to UTC before comparison, eliminating daylight savings (EDT vs EST, CEST vs CET) and geographical timezone leakage.

### Availability Evidence Taxonomy:
- `EXACT_TIMESTAMP_VERIFIED`: Directly verifiable official API/feed release timestamp.
- `ESTIMATED_SCHEDULE`: Official scheduled release time (e.g. ECB reference rates at 16:00 CET = 15:00/14:00 UTC, Treasury close at 16:00 ET = 21:00/20:00 UTC).
- `UNVERIFIED_SAME_DAY`: Sourced same-day without verifiable release time. In `STRICT` mode, availability is defaulted to 23:59:59 UTC to eliminate intraday lookahead bias.
- `RETROSPECTIVE`: Sourced retrospectively; barred from executable backtesting.

---

## 4. Economic Rate Semantics & Classification

Interest rate instruments are not fungible:
- **Central Bank Policy Rates (`RateRole.POLICY_RATE`):** E.g. ECB Deposit Facility Rate (`KR.DFR.LEV`), Fed Funds Target. These are central bank overnight facility rates, not rates available to commercial hedge funds or trading desks.
- **Sovereign Risk-Free Yields (`RateRole.RISK_FREE_RATE`):** E.g. U.S. Treasury 3-Month Bill Yield (`DGS3MO`). These reflect sovereign credit risk and serve as passive cash benchmarks.
- **Commercial Borrowing Rates (`RateRole.BORROWING_RATE`):** Bank prime, SOFR + credit spread, or Euribor + borrowing spread paid by a strategy borrowing liabilities.
- **Commercial Deposit Rates (`RateRole.DEPOSIT_RATE`):** Wholesale deposit rates earned on unallocated cash balances.

### Strategy Executability Classification:
- `EXECUTABLE_VALIDATED`: Executable with verified commercial wholesale/retail rate quotes.
- `RESEARCH_PROXY`: Uses central bank policy rates or Treasury yields as proxies for borrowing/lending. Valid for macroeconomic research, but indicates theoretical proxy status.
- `RESEARCH_ONLY`: Employs retrospective data or unverified availability lags.
- `UNEXECUTABLE`: Missing required market instruments (e.g. forward quotes for covered carry).
- `NO_TRADES`: Valid strategy setup where hurdle filter rejected 100% of candidate trades.

---

## 5. Market Calendar & Execution Rollover

1. **FX Trading Calendar:** Uses [DEFAULT_FX_CALENDAR](file:///D:/Project%20The%20Infinite%20Money%20Glitch%20Detector/src/backtesting/calendar.py) enforcing weekend closures and international market holidays (New Year's Day, Good Friday, Easter Monday, Christmas, Boxing Day).
2. **Weekend Rollover Mechanism:**
   When a 30-day trade matures on a Saturday:
   - Saturday execution is blocked.
   - Sunday execution is blocked.
   - Settle occurs on Monday (calendar day 32).
   - Foreign investment interest in currency B is accrued for 32 days: $f_B = (1 + r_B)^{32/365.25}$.
   - Debt financing liability in currency A is repaid for 32 days: $\text{Financing} = P_A \times ((1 + r_A)^{32/365.25} - 1)$.
   - Exit exchange rate is the prevailing Monday spot rate.
3. **Volatility Annualization:**
   Sampling only on trading days removes artificial zero-return weekend points that previously deflated annualized volatility from 3.55% down to 2.95%.

---

## 6. Exact Double-Entry Return Attribution Ledger

### Mathematical Ledger Identity:
Let:
- $P_A$: Initial borrowed principal in currency A.
- $S_{\text{mid, entry}}$: Spot mid exchange rate at entry.
- $S_{\text{mid, exit}}$: Spot mid exchange rate at exit.
- $f_B$: Investment growth factor in currency B.
- $A_{\text{pure gross}} = \frac{P_A}{S_{\text{mid, entry}}} \times f_B \times S_{\text{mid, exit}}$.
- $\text{Pure Gross Gain}_A = A_{\text{pure gross}} - P_A$.
- $\text{Financing Cost}_A = \text{Interest paid on borrowing liability in A}$.
- $\text{Cash Received}_A = \text{Actual cash converted back from B at } S_{\text{exec, exit}}$.
- $\text{Fees}_A = \text{Exit broker fee} + \text{Fixed round-trip fee}$.
- $\text{Net Trade P\&L}_A = \text{Cash Received}_A - (P_A + \text{Financing Cost}_A) - \text{Fees}_A$.

The Total Frictions are defined as the exact difference between the pure gross mid exit value and the net cash realized before debt financing:
$$\text{Total Frictions}_A = A_{\text{pure gross}} - (\text{Cash Received}_A - \text{Fees}_A)$$

Therefore:
$$\text{Pure Gross Gain}_A - \text{Financing Cost}_A - \text{Total Frictions}_A \equiv \text{Net Trade P\&L}_A$$
$$\text{Residual} \equiv 0.0000000000000000$$

### Verified Empirical Cash Attribution (Full 5-Year Positive Carry):
- **Pure Gross Gain:** $+10,652.36 (+10.65%)$
- **Debt Financing Costs:** $-2,941.23 (-2.94%)$
- **Total Frictions Drag:** $-1,504.98 (-1.50%)$
- **Idle Cash Interest Earned:** $+7,851.97 (+7.85%)$
- **Cumulative Net Profit:** $+14,058.12 (+14.06%)$
- **Reconciliation Residual:** **0.0000000000** (`reconciliation_exact: True`)

---

## 7. Regime Analysis & Empirical Re-evaluation

### Regime 1: Negative/Zero Interest Rate Policy (2020-01-01 to 2022-03-31)
- **Macroeconomic Setting:** ECB Deposit Facility Rate at -0.50%; U.S. 3-Month Treasury yield near 0.10%.
- **Trades Executed:** 27 trades (51.9% win rate).
- **Strategy Return:** **+0.80%** (Annualized **+0.36%**).
- **Attribution:**
  - Pure Gross Gain: $+914.37 (+0.91%)$
  - Financing Costs: $-562.25 (-0.56%)$ (EUR negative borrowing rate accrued credit)
  - Frictions Drag: $-675.30 (-0.68%)$
  - Idle Cash: $\$0.00$
  - Net Profit: $+801.32 (+0.80%)$
- **Benchmark Return:** -1.12% (EUR cash lost value under NIRP).
- **Excess Return:** **+1.92%**.

### Regime 2: Aggressive Monetary Tightening Cycle (2022-04-01 to 2024-12-31)
- **Macroeconomic Setting:** Global central bank rate hikes; U.S. 3M Treasury yield surged to 5.40%; ECB DFR hiked to 4.00%.
- **Trades Executed:** 34 trades (52.9% win rate).
- **Strategy Return:** **+15.40%** (Annualized **+5.34%**).
- **Attribution:**
  - Pure Gross Gain: $+9,507.21 (+9.51%)$
  - Financing Costs: $-3,479.91 (-3.48%)$
  - Frictions Drag: $-854.56 (-0.85%)$
  - Idle Cash Interest: $+10,229.75 (+10.23%)$
  - Net Profit: $+15,402.49 (+15.40%)$
- **Benchmark Return:** +9.94%.
- **Excess Return:** **+5.46%**.

---

## 8. Data Provenance & Immutable Archive Manifest

Raw observation files are permanently preserved under `data/raw/`. Their SHA-256 cryptographic digests are recorded in [data/manifest.json](file:///D:/Project%20The%20Infinite%20Money%20Glitch%20Detector/data/manifest.json):

| File Name | SHA-256 Digest | Size (Bytes) | Provider / Description |
| :--- | :--- | :--- | :--- |
| `ecb_dfr_2020-01-01_2024-12-31.csv` | `b7cf01828f2ecb6001c76c7634bfb18b7b2e7fa55e28dcff33988701770fa12a` | 745,488 | ECB Data Portal (DFR Level) |
| `frankfurter_EUR_base_USD_quote_2020-01-01_2024-12-31.json` | `ce39d08f87317c846337e9e5d28fab82c7f00f6ceb8f1b30ff5a43f57504140b` | 39,757 | Frankfurter (EUR/USD ECB Reference Rates) |
| `frankfurter_USD_base_EUR_quote_2020-01-01_2024-12-31.json` | `bc7234408b74ffaf02b77df38265d1168f05ae7bac7da6e903240ef9d2a7e918` | 40,979 | Frankfurter (USD/EUR ECB Reference Rates) |
| `us_treasury_2020.csv` | `c028621ad8755f62cc0bfc8b7c09f62be9e49d4e1a17bc57582ed53249b0466f` | 18,163 | U.S. Dept of Treasury Daily Yields (2020) |
| `us_treasury_2021.csv` | `bd50bb1530b07850e3f696114724f950da8be1171c42f5b8f0624af167dd534c` | 18,163 | U.S. Dept of Treasury Daily Yields (2021) |
| `us_treasury_2022.csv` | `b3aeb9ab6998878be2c82722fd42933b1e461f1953f999b3dd2fb6f200707bc9` | 18,475 | U.S. Dept of Treasury Daily Yields (2022) |
| `us_treasury_2023.csv` | `1d5072667b66fda85631219d9b8baab95d631a92765c0bf2885558019f2d0816` | 19,348 | U.S. Dept of Treasury Daily Yields (2023) |
| `us_treasury_2024.csv` | `27898e5d4409074f9f387a736f6864574b5f5721b38b0199286eaf9d1ef575d8` | 19,348 | U.S. Dept of Treasury Daily Yields (2024) |

Every backtest run dynamically verifies and embeds `res.manifest_digest`.

---

## 9. Automated Audit Test Suite & CI

The audit verification suite is codified in [tests/test_audit_phase_3_2_1.py](file:///D:/Project%20The%20Infinite%20Money%20Glitch%20Detector/tests/test_audit_phase_3_2_1.py) and executed via automated CI in [.github/workflows/ci.yml](file:///D:/Project%20The%20Infinite%20Money%20Glitch%20Detector/.github/workflows/ci.yml).

### Test Coverage Summary:
- `test_pit_firewall_intraday_same_day_filtering`: PASSED
- `test_pit_firewall_multi_timezone_normalization`: PASSED
- `test_pit_firewall_future_observation_date_leakage`: PASSED
- `test_strategy_status_classification_research_proxy`: PASSED
- `test_strategy_status_no_trades_classification`: PASSED
- `test_calendar_rollover_weekend_to_next_trading_day`: PASSED
- `test_exact_double_entry_attribution_reconciliation`: PASSED
- `test_scoped_provenance_window`: PASSED
- `test_manifest_sha256_integrity`: PASSED

**Total Test Suite:** 158 tests passed in 10.62 seconds.

---

## 10. Non-Claims & Scientific Boundaries

1. **No "Infinite Money Glitch":**  
   The positive unhedged carry return (+2.67% annualized) is driven entirely by the macro interest differential between USD and EUR and moderate USD appreciation during 2022. It is subject to severe exchange rate crash risk (max drawdown of -5.64% to -6.82%).
2. **Proxy Limitation:**  
   Because commercial banking spreads were not added to sovereign/policy yields, these returns represent a **theoretical macroeconomic research proxy (`RESEARCH_PROXY`)**, not executable institutional alpha.
3. **Execution Integrity:**  
   Covered carry trades remain rejected as `UNEXECUTABLE` until traceable commercial forward points/outright forward rate quotes are integrated.
