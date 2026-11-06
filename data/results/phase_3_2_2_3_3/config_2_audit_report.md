# Historical Backtest Execution Report
**Strategy**: `Config 2: Estimated-Availability Reference-Rate Research`  
**Currency Pair**: `EUR/USD`  
**Simulation Window**: `2020-01-01` to `2024-12-31`  
**Initial Capital**: `100,000.00 EUR`  
**Trade Tenor**: `30 calendar days`  
**Data Availability Policy**: `ESTIMATED_LAG`  
**PIT Availability Status**: `ESTIMATED_AVAILABILITY`  
**PIT Credible**: `NO`  
**Executable Strategy**: `NO`  

## 1. Performance and Risk Summary

| Metric | Value | Convention / Assumption |
| :--- | :--- | :--- |
| **Cumulative Net Profit** | `2,890.22 EUR` | Sum of net PnL after financing & fees |
| **Total Return** | `+2.89%` | Cumulative profit / initial capital |
| **Annualized Return** | `+0.57%` | Compounded equivalent annual rate |
| **Annualized Volatility** | `2.98%` | Sample std (ddof=1) of periodic returns * sqrt(252) |
| **Sharpe Ratio** | `-0.04` | Excess return over borrowing cash rate |
| **Sortino Ratio** | `-0.06` | Downside deviation below risk-free rate |
| **Maximum Drawdown** | `-3.52%` | Peak-to-trough compounded equity decline |
| **Calmar Ratio** | `0.16` | Annualized return / abs(Max Drawdown) |
| **Value at Risk (95% VaR)** | `-0.31%` | Empirical lower 5th percentile of period returns |
| **Conditional VaR (95% CVaR)** | `-0.49%` | Expected shortfall of returns at/below VaR |
| **Average Capital Utilization** | `22.8%` | Mean borrowed exposure / equity |
| **Peak Exposure** | `54,582.65 EUR` | Maximum simultaneous borrowed principal |

## 2. Return Attribution Decomposition & Double-Entry Cash Ledger

| Attribution Component | Currency Amount | Return on Capital | Description |
| :--- | :--- | :--- | :--- |
| **Pure Gross Gain** | `-218.74 EUR` | `-0.2187%` | Asset appreciation & interest before financing & fees |
|   ├── *Pure FX Movement* | `-5,655.77 EUR` | `-5.6558%` | FX spot price change on invested capital |
|   └── *Investment Asset Yield* | `+5,437.03 EUR` | `+5.4370%` | Interest accrued on investment asset |
| **Debt Financing Costs** | `-3,683.87 EUR` | `-3.6839%` | Interest paid on borrowed liabilities |
| **Execution Frictions Drag** | `-910.04 EUR` | `-0.9100%` | Total bid/ask spread, slippage, and ticket fees |
|   ├── *Observed Spread Cost* | `-0.00 EUR` | `-0.0000%` | Market bid/ask spread paid |
|   ├── *Modelled Spread Cost* | `-306.02 EUR` | `-0.3060%` | Synthetic parameter spread paid |
|   └── *Execution Slippage* | `-153.00 EUR` | `-0.1530%` | Execution timing slippage |
| **Cash Yield on Unallocated Balances** | `+7,702.87 EUR` | `+7.7029%` | Interest earned on cash balances |
| **Reconciled Net Profit** | `**+2,890.22 EUR**` | `**+2.8902%**` | Gross Gain - Financing - Fees + Cash Yield |
| **Reconciliation Residual** | `**+0.0000000000**` | `Exact: True` | Absolute residual ($|\text{residual}| \le 10^{-10}$) |
| **Position-Level Volatility** | `6.20%` | Volatility evaluated on active deployed capital (undiluted) |
| **Portfolio-Level Volatility** | `2.98%` | Volatility evaluated on total portfolio equity |

## 3. Trade Execution Statistics

| Metric | Value |
| :--- | :--- |
| **Total Closed Trades** | `29` |
| **Winning Trades** | `13` |
| **Losing Trades** | `16` |
| **Win Rate** | `44.8%` |
| **Average Winning Trade** | `933.95 EUR` |
| **Average Losing Trade** | `-1,059.62 EUR` |
| **Profit Factor** | `0.72` |
| **Rejected Trade Attempts** | `31` |

## 4. Benchmark Comparison & Excess Returns

**Comparative Benchmark**: `EUR Fixed Deposit Proxy (1.5% annual)`  
- Benchmark Total Return: `+7.7284%`  
- Benchmark Annualized Return: `+1.5000%`  
- Strategy Total Return: `+2.8902%`  
- Strategy Annualized Return: `+0.5715%`  
- Cumulative Excess Return: `-4.8382%`  
- Annualized Excess Return: `-0.9285%`  
- Strategy Alpha (Excess Return): `-0.9285%`  

## 5. Historical Information Firewall Audit

- **Availability Policy**: `ESTIMATED_LAG`
- **Max permissible staleness**: `5 trading days`
- **Total Audit Log Entries**: `59`
- **Rejections Recorded**: `31` (Reasons include capital limits, missing quotes, hurdle rate)

## 6. Data Provenance & Traceability Report

- **Source Providers**: `ecb, frankfurter, us_treasury, world_bank`
- **Dataset Identifiers**: `DGS1MO, DGS3MO, FP.CPI.TOTL.ZG, KR.DFR.LEV, KR.MRR_FR.LEV`
- **Date Range**: `2020-01-01` to `2024-12-31` (`1827` calendar days, `1297` trading days)
- **Publication Timestamps Populated**: `0.0%` (0 / 8,737 observations)
- **Exact Publication Timestamps Verified**: `0.0%` (0 / 8,737 observations)
- **Estimated Publication Schedule**: `99.8%` (8,722 / 8,737 observations)
- **Retrospective Research**: `0.2%` (15 / 8,737 observations)
- **Classification Breakdown**: `real_retrospective = 15, real_verified = 8722`
- **Audit Declaration**: DATA PROVENANCE VERIFIED: 100% genuine historical observations from registered sources: ecb, frankfurter, us_treasury, world_bank. Publication timestamps populated: 0.0% (independently verified EXACT_TIMESTAMP_VERIFIED: 0.0%). Trading day quote coverage: 98.8%.