# Historical Backtest Execution Report
**Strategy**: `Config 2: Estimated-Availability Reference-Rate Research`  
**Currency Pair**: `EUR/USD`  
**Simulation Window**: `2020-01-01` to `2024-12-31`  
**Initial Capital**: `100,000.00 EUR`  
**Trade Tenor**: `30 calendar days`  
**Data Availability Policy**: `ESTIMATED_LAG`  
**Executable Strategy**: `NO`  

## 1. Performance and Risk Summary

| Metric | Value | Convention / Assumption |
| :--- | :--- | :--- |
| **Cumulative Net Profit** | `2,906.92 EUR` | Sum of net PnL after financing & fees |
| **Total Return** | `+2.91%` | Cumulative profit / initial capital |
| **Annualized Return** | `+0.57%` | Compounded equivalent annual rate |
| **Annualized Volatility** | `3.74%` | Sample std (ddof=1) of periodic returns * sqrt(252) |
| **Sharpe Ratio** | `-0.04` | Excess return over borrowing cash rate |
| **Sortino Ratio** | `-0.05` | Downside deviation below risk-free rate |
| **Maximum Drawdown** | `-9.13%` | Peak-to-trough compounded equity decline |
| **Calmar Ratio** | `0.06` | Annualized return / abs(Max Drawdown) |
| **Value at Risk (95% VaR)** | `-0.40%` | Empirical lower 5th percentile of period returns |
| **Conditional VaR (95% CVaR)** | `-0.54%` | Expected shortfall of returns at/below VaR |
| **Average Capital Utilization** | `45.6%` | Mean borrowed exposure / equity |
| **Peak Exposure** | `50,000.00 EUR` | Maximum simultaneous borrowed principal |

## 2. Return Attribution Decomposition & Double-Entry Cash Ledger

| Attribution Component | Currency Amount | Return on Capital | Description |
| :--- | :--- | :--- | :--- |
| **Pure Gross Gain** | `-443.92 EUR` | `-0.4439%` | Asset appreciation & interest before financing & fees |
|   ├── *Pure FX Movement* | `-6,714.52 EUR` | `-6.7145%` | FX spot price change on invested capital |
|   └── *Investment Asset Yield* | `+6,270.59 EUR` | `+6.2706%` | Interest accrued on investment asset |
| **Debt Financing Costs** | `-2,922.32 EUR` | `-2.9223%` | Interest paid on borrowed liabilities |
| **Execution Frictions Drag** | `-1,499.54 EUR` | `-1.4995%` | Total bid/ask spread, slippage, and ticket fees |
|   ├── *Observed Spread Cost* | `-0.00 EUR` | `-0.0000%` | Market bid/ask spread paid |
|   ├── *Modelled Spread Cost* | `-599.82 EUR` | `-0.5998%` | Synthetic parameter spread paid |
|   └── *Execution Slippage* | `-299.89 EUR` | `-0.2999%` | Execution timing slippage |
| **Cash Yield on Unallocated Balances** | `+7,772.70 EUR` | `+7.7727%` | Interest earned on cash balances |
| **Reconciled Net Profit** | `**+2,906.92 EUR**` | `**+2.9069%**` | Gross Gain - Financing - Fees + Cash Yield |
| **Reconciliation Residual** | `**+0.0000000000**` | `Exact: True` | Absolute residual ($|\text{residual}| \le 10^{-10}$) |
| **Position-Level Volatility** | `8.18%` | Volatility evaluated on active deployed capital (undiluted) |
| **Portfolio-Level Volatility** | `3.74%` | Volatility evaluated on total portfolio equity |

## 3. Trade Execution Statistics

| Metric | Value |
| :--- | :--- |
| **Total Closed Trades** | `60` |
| **Winning Trades** | `28` |
| **Losing Trades** | `32` |
| **Win Rate** | `46.7%` |
| **Average Winning Trade** | `866.13 EUR` |
| **Average Losing Trade** | `-909.92 EUR` |
| **Profit Factor** | `0.83` |
| **Rejected Trade Attempts** | `0` |

## 4. Benchmark Comparison & Excess Returns

**Comparative Benchmark**: `EUR Fixed Deposit Proxy (1.5% annual)`  
- Benchmark Total Return: `+7.7284%`  
- Benchmark Annualized Return: `+1.5000%`  
- Strategy Total Return: `+2.9069%`  
- Strategy Annualized Return: `+0.5747%`  
- Cumulative Excess Return: `-4.8215%`  
- Annualized Excess Return: `-0.9253%`  
- Strategy Alpha (Excess Return): `-0.9253%`  

## 5. Historical Information Firewall Audit

- **Availability Policy**: `ESTIMATED_LAG`
- **Max permissible staleness**: `5 trading days`
- **Total Audit Log Entries**: `121`

## 6. Data Provenance & Traceability Report

- **Source Providers**: `ecb, frankfurter, us_treasury, world_bank`
- **Dataset Identifiers**: `DGS1MO, DGS3MO, FP.CPI.TOTL.ZG, KR.DFR.LEV, KR.MRR_FR.LEV`
- **Date Range**: `2020-01-01` to `2024-12-31` (`1827` calendar days, `1297` trading days)
- **Missing Trading Days Quote Coverage**: `1.2%` missing trading-day quotes
- **Verified Publication Dates**: `99.8%` of observations have verified publication timestamps
- **Observation Counts**: Total = `8737`, Real = `8737`, Synthetic = `0`
- **Classification Breakdown**: `real_retrospective = 15, real_verified = 8722`
- **Audit Declaration**: DATA PROVENANCE VERIFIED: 100% genuine historical observations from registered sources: ecb, frankfurter, us_treasury, world_bank. Verified publication date availability: 99.8%. Trading day quote coverage: 98.8%.