# Phase 3.2: Initial Repository Architecture & Data Integrity Audit
**Project:** The Infinite Money Glitch Detector  
**Audit Timestamp:** 2026-11-05  
**Baseline Test Suite:** 143 tests passing (100% pass rate)

---

## 1. Executive Summary

This initial audit establishes the architectural state of the repository prior to implementing Phase 3.2 (Real Market Data Validation). The core directive of Phase 3.2 is:
> **Mathematics first. Data second. Prediction third. AI last.**  
> Validate against genuine, traceable historical financial data across distinct market regimes without synthetic filler, fabricated forward quotes, or forward-filling missing observations.

---

## 2. Repository Architecture Review

```
src/
├── core/                  # Deterministic math: conversions, currency, interest
├── data/
│   ├── adapters/          # Source adapters: Frankfurter, ECB, FRED, World Bank, IMF
│   ├── db/                # SQLAlchemy ORM models (models.py) & engine (engine.py)
│   ├── http.py            # Retry-enabled HTTP transport client
│   ├── ingest.py          # Adapter -> Quality -> Repository pipeline
│   ├── quality.py         # Outlier, jump, negative rate, and ordering rules
│   ├── repository.py      # Idempotent persistence, revisions, PIT queries
│   └── schemas.py         # Canonical Pydantic schemas (DataObservation, FetchResult)
├── models/
│   ├── carry_trade.py     # Unhedged & covered carry trade models
│   ├── ppp.py             # Purchasing Power Parity models
│   └── risk.py            # Historical volatility, VaR, CVaR, Sharpe, Max Drawdown
├── backtesting/
│   ├── engine.py          # Core backtest simulation loop
│   ├── portfolio.py       # Portfolio cash, leverage, position tracking, cash yield
│   ├── execution.py       # Order execution, slippage, bid/ask spreads, ticket fees
│   ├── financing.py       # Loan borrowing and repayment accounting
│   ├── valuation.py       # Mark-to-market portfolio snapshots
│   ├── signals.py         # Unhedged and covered carry signal generators
│   ├── metrics.py         # Risk & performance metrics, return attribution
│   ├── benchmarks.py      # Cash borrowing benchmark, passive FX holding, CIP
│   ├── walk_forward.py    # Purged/embargoed rolling & expanding window splits
│   ├── point_in_time.py   # Historical Information Firewall (Strict, Est, Research)
│   ├── reporting.py       # Formatted markdown backtest & walk-forward reports
│   ├── calendar.py        # FX market calendar, trading day lags, holiday tracking
│   └── provenance.py      # Data provenance and traceability auditor
├── schemas/
│   ├── strategy.py        # Strategy configuration contracts
│   └── backtest.py        # ExecutionConfig, AvailabilityConfig, BacktestResult
└── simulation/
    └── sensitivity.py     # Parameter sensitivity and scenario analysis
```

---

## 3. Dataset Provenance & Classification Audit

An exhaustive inspection of the existing database (`data/processed/gmdb.db`), tests, and scripts categorized all active historical observations into four distinct categories:

### A. Genuine Provider Observations
* **Frankfurter (ECB Daily Reference Rates):**
  * 23 rows of USD/BRL rates (`2026-10-02` to `2026-11-03`) currently stored in `gmdb.db`.
  * Real-time network probe confirmed live access to 2,306 genuine daily USD/EUR observations covering `2016-01-01` to `2024-12-31`.
  * Verified same-day publication timestamp.
* **ECB Data Portal (Euro Area Policy Rates):**
  * Official daily Deposit Facility Rate (`KR.DFR.LEV` / `FM.D.U2.EUR.4F.KR.DFR.LEV`).
  * Real-time network probe confirmed 3,288 genuine daily observations covering `2016-01-01` to `2024-12-31` (negative -0.50% to +4.00%).
* **US Department of the Treasury (Fiscal Data / Par Yield Curve):**
  * Official daily Constant Maturity Treasury rates (1-month, 3-month, 6-month, 1-year risk-free yields) covering 2016–2024 with ~250–252 trading days per year.

### B. Synthetic / Generated Observations
* **In-Memory Synthetic Data Generator (`examples/run_historical_backtest.py`):**
  * 2,735 daily synthetic observations generated in-memory (`2023-01-01` to `2024-06-30`).
  * Used `0.0002 * (days % 14 - 7)` wave function for USD/EUR, and linear depreciation for USD/TRY.
  * Properly flagged with `is_synthetic=True`.
* **Database Synthetic Demo Rows:**
  * 8 rows in `data_observation` table with `source_id='synthetic_demo'` (`AAA`, `BBB`).
  * Permanently marked with `is_synthetic=True`.

### C. Mocked API Responses
* **Test Fixtures (`tests/test_adapters.py`, `tests/test_ingest.py`, etc.):**
  * Use `httpx.MockTransport` or deterministic JSON dictionaries.
  * Used solely to verify adapter parsing, error handling, and schema validation.
  * Completely separated from persistent historical datasets.

### D. Retrospectively Retrieved Observations Without Verified Publication Timestamps
* **World Bank Open Data (`world_bank` in `gmdb.db`):**
  * 176 rows of annual CPI indicators for BRA, JPN, USA (`1960` to `2025`).
  * Published months or years after the calendar year closed; `publication_date` was not provided in original source payloads.
  * In `Strict` PIT mode, these are properly excluded from historical signals unless an estimated lag policy is declared.

---

## 4. Phase 3.1 Quantitative Audit Findings & Preservation

Phase 3.1 resolved critical quantitative defects that must be preserved:
1. **Benchmark Comparability & Interest Rate Hierarchy:**
   * Distinguishes `BORROWING_RATE`, `DEPOSIT_RATE`, `POLICY_RATE`, and `RISK_FREE_RATE`.
   * Strategy unallocated cash accrues deposit interest; cash benchmark accrues deposit interest (not borrowing rate).
   * Exact return attribution decomposition:
     $$\text{Net Return} = R_{\text{gross foreign}} - D_{\text{financing}} - D_{\text{execution fees}} + R_{\text{cash yield}}$$
2. **Volatility Measurement & Capital Dilution:**
   * Distinguishes `position_annualized_volatility` (on deployed active capital) from `annualized_volatility` (on total equity).
   * Uses `MarketCalendar` to sample strictly over active FX trading days (252 periods/year), eliminating artificial zero returns from weekends.
3. **Maximum Drawdown Initial Wealth Bug Fix:**
   * In `src/models/risk.py`, fixed `wealth = np.insert(np.cumprod(1.0 + r), 0, 1.0)` so drawdowns occurring in period 1 from starting capital are captured.
4. **Adversarial Point-in-Time Revision Integrity:**
   * Verified that multi-revision restatements and delayed releases never leak into prior signals.

---

## 5. Scope & Action Plan for Phase 3.2

To fulfill Phase 3.2 without regressing existing functionality:
1. **Data Classification Taxonomy:**
   * Introduce `DataClassification` (`REAL_VERIFIED`, `REAL_ESTIMATED_AVAILABILITY`, `REAL_RETROSPECTIVE`, `SYNTHETIC`, `MOCK`).
   * Enforce that `STRICT` PIT mode permits only `REAL_VERIFIED` data.
2. **US Treasury / Federal Reserve Real Interest Rate Adapter:**
   * Build an official, keyless, reliable adapter for US Treasury daily yield curve rates (1-month / 3-month risk-free yields) directly from the US Department of the Treasury.
3. **ECB Real Interest Rate Adapter Correction:**
   * Fix the series key in `EcbPolicyRateAdapter` to `FM.D.U2.EUR.4F.KR.DFR.LEV` with proper timeout handling to stream official daily ECB deposit facility rates.
4. **Multi-Regime Historical Dataset Ingestion:**
   * Ingest 5+ years (2020–2024) of daily genuine USD/EUR reference rates from Frankfurter, daily ECB deposit rates, and daily US Treasury risk-free/deposit rates into `gmdb.db` with complete raw payload archiving.
   * Span Regime 1 (2020–2022: Negative/zero rates, compressed differentials) and Regime 2 (2022–2024: Rapid Fed/ECB rate hiking cycles, dollar parity stress).
5. **Real-Data Backtesting & Market Regime Validation:**
   * Execute unhedged carry trade, cash benchmark, and CIP diagnostic on genuine historical data.
   * Verify return attribution, trading calendar alignment, and lack of forward-filling.
   * Document all findings in `PHASE_3_2_REAL_DATA_VALIDATION.md`.
