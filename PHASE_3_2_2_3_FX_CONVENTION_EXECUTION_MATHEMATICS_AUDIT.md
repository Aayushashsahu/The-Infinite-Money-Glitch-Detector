# PHASE 3.2.2.3 — CANONICAL FX CONVENTION & EXECUTION MATHEMATICS AUDIT REPORT
## The Infinite Money Glitch Detector

> **Guiding Principle: Mathematics first. Data second. Prediction third. AI last.**  
> *We are not trying to make the backtest more profitable. We are trying to make it more correct.*

---

## Executive Summary

Phase 3.2.2.3 completes a rigorous mathematical and structural audit of currency exchange-rate conventions, conversion formulas, executable bid/ask mechanics, quote freshness rules, and transaction cost accounting across the historical backtesting engine.

A foundational mathematical discrepancy was identified and resolved:
1. **Mathematical Core Definition** (`src/core/currency.py`, `README.md`): Exchange rates are defined as units of borrowing currency $A$ per 1 unit of investment currency $B$ ($X = A/B$). Converting $A \to B$ divides by $X$, and converting $B \to A$ multiplies by $X$.
2. **Provider Market Quoting** (`src/data/adapters/frankfurter.py`): Market exchange rates are quoted as units of quote currency per 1 unit of base currency (`QUOTE_PER_BASE`), e.g., $\text{EUR/USD} = 1.10$ signifies $1.10\text{ USD per 1 EUR}$.
3. **The Inversion Conflict**: For an unhedged carry trade borrowing EUR ($A$) and investing in USD ($B$), the canonical rate required by the core formulas is $X = \text{EUR per USD} = 1.0 / 1.10 = 0.909091$. In previous versions (Phase 3.2 through 3.2.2.2), the raw market quote $1.10$ was passed unnormalized into `convert_to_b()`, which computed $100,000 / 1.10 = \$90,909.09$ instead of €$100,000 \times 1.10 = \$110,000.00$. This inverted the foreign currency exposure and reversed the sign of spot FX price translation gains and losses.

When this mathematical inversion is corrected:
- The **pure gross trade profit** of the 2020–2024 EUR/USD carry trade drops from $+10,652.20\text{ EUR}$ to **$-443.92\text{ EUR}$** ($-0.44\%$ on capital).
- The strategy suffered **$-6,714.52\text{ EUR}$** ($-6.71\%$) in pure spot FX depreciation losses during the 2021–2022 USD cycles, partially offset by **$+6,270.59\text{ EUR}$** ($+6.27\%$) in USD yield, while paying **$-2,922.32\text{ EUR}$** in borrowing financing costs and **$-1,499.54\text{ EUR}$** in execution frictions.
- Unallocated cash earned **$+7,772.70\text{ EUR}$** ($+7.77\%$) in cash deposit yield, resulting in a net portfolio profit of **$+2,906.92\text{ EUR}$** (**$+2.91\%$** total return, $+0.57\%$ annualized).
- Compared against the matched 1.5% EUR cash deposit benchmark ($+7.73\%$ total return, $+1.50\%$ annualized), the strategy generated an annualized alpha of **$-0.93\%$** and an annualized Sharpe ratio of **$-0.04$**. The strategy underperformed risk-free cash deposit holding.

---

## 1. Original Convention Conflict

The codebase previously exhibited a conflict between the market quoting conventions used by external data providers and the internal mathematical definitions used by the currency conversion module:

| Component | Convention Used | Interpretation of EUR/USD = 1.10 | Mathematical Meaning |
| :--- | :--- | :--- | :--- |
| **`core.currency`** | Units of A per 1 unit of B | 1.10 EUR per 1 USD | Converting $A \to B$ divides by rate; $B \to A$ multiplies. |
| **`adapters.frankfurter`** | Standard ISO market quote (`QUOTE_PER_BASE`) | 1.10 USD per 1 EUR | $1\text{ EUR} = 1.10\text{ USD}$. Standard FX market quotation. |
| **`backtesting.engine`** (Legacy) | Requested pair code `"EUR/USD"` | Treated provider value 1.10 directly as $A/B$ | Evaluated EUR principal with inverted scaling ($100,000 / 1.10 = \$90,909$). |

### The Root Cause of Distorted Historical Returns
Under the legacy approach:
$$\text{Principal in USD} = \frac{L_A}{X_0} = \frac{100,000\text{ EUR}}{1.10} = \$90,909.09$$
When the exchange rate dropped to $0.96$ in late 2022 (strong USD appreciation):
$$\text{Exit Value in EUR} = \text{Principal in USD} \times X_1 = \$90,909.09 \times 0.96 = 87,272.73\text{ EUR}$$
The trade was recorded as losing money on the USD rise, whereas borrowing EUR to hold appreciating USD actually generated substantial FX gains. Conversely, during periods of EUR recovery (USD depreciation), the inverted formulas registered synthetic FX profits. In total, the legacy +14.08% return was an artifact of inverted foreign exchange translation mathematics.

---

## 2. Selected Canonical Convention & Rationale

We selected and standardized on a single, mathematically rigorous canonical convention throughout the entire simulation pipeline:

### Canonical Convention: Units of Borrowing Currency A per 1 Unit of Investment Currency B ($rate_{A/B}$)
$$\text{Rate}_{A/B} = \frac{\text{Units of Borrowing Currency } A}{\text{1 Unit of Investment Currency } B}$$

### Rationale:
1. **Mathematical Consistency with Core Carry Trade Formula**:
   $$\text{Profit}_A = L_A \left[ (1 + r_B \cdot t) \frac{X_1}{X_0} - (1 + r_A \cdot t) \right] - C_A$$
   When $X$ is defined as units of $A$ per unit of $B$, the ratio $X_1 / X_0$ represents the direct appreciation factor of the investment currency $B$ relative to liability currency $A$. If $B$ appreciates, $X_1 > X_0 \implies X_1 / X_0 > 1$, which increases $\text{Profit}_A$.
2. **Explicit Conversion Semantics**:
   - Converting $A \to B$: $\text{Amount}_B = \frac{\text{Amount}_A}{rate_{A/B}}$
   - Converting $B \to A$: $\text{Amount}_A = \text{Amount}_B \times rate_{A/B}$
3. **Double-Entry Accounting Preservation**:
   All balance sheet liabilities, debt financing accrued, transaction frictions, cash interest, and mark-to-market valuations are natively denominated in borrowing currency $A$ without requiring dual-currency balance sheet conversions.

---

## 3. Provider Normalization Specification

Market data providers do not quote currency pairs in a uniform direction. To ensure mathematical isolation, data ingestion adapters now attach explicit quotation metadata to every observation.

### Schema Additions (`src/data/schemas.py`):
```python
class QuoteConvention(str, Enum):
    QUOTE_PER_BASE = "quote_per_base"  # Standard FX market: quote currency units per 1 base currency unit
    BASE_PER_QUOTE = "base_per_quote"  # Inverted quote: base currency units per 1 quote currency unit

class DataObservation(BaseModel):
    # Canonical currency pair metadata
    base_currency: str | None = None
    quote_currency: str | None = None
    quote_convention: QuoteConvention = QuoteConvention.QUOTE_PER_BASE
    bid: float | None = None
    ask: float | None = None
```

### Provider Ingestion Rules (`src/data/adapters/frankfurter.py`):
- For `EUR/USD` from Frankfurter (ECB reference rate):
  - `entity_code = "EUR/USD"`
  - `base_currency = "EUR"`
  - `quote_currency = "USD"`
  - `quote_convention = QuoteConvention.QUOTE_PER_BASE`
  - `raw_provider_value = 1.0850` (signifies $1.0850\text{ USD per 1 EUR}$)

### Canonical Conversion Layer (`src/core/currency.py`):
`get_rate_a_per_b(value, obs_base, obs_quote, borrowing_currency, investment_currency, convention)` maps any observed rate into canonical $rate_{A/B}$:
1. If observation is quoted as `QUOTE_PER_BASE` ($base / quote$):
   - If $A == base$ and $B == quote$: $rate_{A/B} = \frac{1.0}{value}$ (units of $A$ per $B$).
   - If $A == quote$ and $B == base$: $rate_{A/B} = value$ (units of $A$ per $B$).
2. Cross rates and reciprocal quotes are converted deterministically without manual inversion.

---

## 4. Reciprocal Quote Handling

In two-way foreign exchange markets, bid and ask prices must be inverted reciprocally to avoid negative synthetic spreads or arbitrage violations.

### Inversion Invariants:
For an executable two-way market quote $(Bid_{quote/base}, Ask_{quote/base})$ where $0 < Bid \le Ask$:
$$\text{Inverse Bid}_{base/quote} = \frac{1.0}{Ask_{quote/base}}$$
$$\text{Inverse Ask}_{base/quote} = \frac{1.0}{Bid_{quote/base}}$$

### Proof of Spread Positivity:
Because $Bid \le Ask$:
$$\frac{1.0}{Ask} \le \frac{1.0}{Bid} \implies \text{Inverse Bid} \le \text{Inverse Ask}$$
The bid-ask spread in reciprocal space is:
$$\text{Spread}_{base/quote} = \frac{1.0}{Bid} - \frac{1.0}{Ask} = \frac{Ask - Bid}{Bid \cdot Ask} \ge 0$$
Implemented in `core.currency.invert_two_way_quote()` and enforced in `DataObservation` invariants. Crossed quotes ($Bid > Ask$) are strictly rejected with `ValueError`.

---

## 5. Currency Conversion Formulas

The complete set of execution and conversion formulas implemented across `src/core/currency.py`, `src/backtesting/execution.py`, and `src/backtesting/point_in_time.py`:

### Trade Entry (Borrow A, Convert to B):
1. **Borrow Principal**: $L_A$ in borrowing currency $A$.
2. **Execution Rate**: Strategy must buy investment currency $B$ using currency $A$. In canonical $rate_{A/B}$ terms, the trader pays the higher offer (ask):
   $$\text{Execution Rate (Ask)}_{A/B} = Ask_{A/B}$$
   $$\text{Invested Amount in } B = \frac{L_A}{\text{Execution Rate (Ask)}_{A/B}}$$

### Trade Exit (Sell B, Repay Liability A):
1. **Gross Growth of Asset B**:
   $$B_{final} = B_{invested} \times \left(1 + r_B \cdot \frac{\Delta t}{360}\right)$$
2. **Execution Rate**: Strategy sells investment currency $B$ to receive borrowing currency $A$. In canonical $rate_{A/B}$ terms, the trader receives the lower bid:
   $$\text{Execution Rate (Bid)}_{A/B} = Bid_{A/B}$$
3. **Gross Proceeds in A**:
   $$A_{gross} = B_{final} \times \text{Execution Rate (Bid)}_{A/B}$$

### Liability Repayment & Net Profit in A:
1. **Liability Accrual**:
   $$A_{liability} = L_A \times \left(1 + r_A \cdot \frac{\Delta t}{360}\right)$$
2. **Financing Cost**:
   $$\text{Financing Cost}_A = L_A \times r_A \cdot \frac{\Delta t}{360}$$
3. **Net Profit**:
   $$\text{Net Profit}_A = A_{gross} - A_{liability} - \text{Fixed Fees}_A - \text{Variable Fees}_A$$

---

## 6. Independent Numerical Examples

To verify the mathematical specification independently of any code, three end-to-end numerical examples were computed by hand and verified by automated unit tests:

### Example 1: EUR/USD Carry Trade (Borrow EUR, Invest USD)
- **Borrowing Currency $A$**: EUR
- **Investment Currency $B$**: USD
- **Borrowed Capital $L_A$**: $100,000.00\text{ EUR}$
- **Market Quote (Frankfurter)**: EUR/USD $= 1.1000$ (i.e. $1.1000\text{ USD per 1 EUR}$)
- **Canonical Conversion**:
  $$rate_{A/B} = \frac{1.0}{1.1000} = 0.90909091\text{ EUR per 1 USD}$$
- **Capital Conversion**:
  $$\text{USD Invested} = \frac{100,000.00\text{ EUR}}{0.90909091} = \$110,000.00\text{ USD}$$
- **Tenor**: 360 days (1 year)
- **Interest Rates**: EUR borrowing rate $r_A = 2.0\%$; USD investment rate $r_B = 5.0\%$
- **Asset Growth in USD**:
  $$B_{final} = \$110,000.00 \times (1 + 0.05) = \$115,500.00\text{ USD}$$
- **Exit Market Quote**: EUR/USD $= 1.1000$ (Spot rate unchanged)
  $$rate_{A/B}^{exit} = \frac{1.0}{1.1000} = 0.90909091\text{ EUR per 1 USD}$$
- **Repatriated EUR Proceeds**:
  $$A_{gross} = \$115,500.00 \times 0.90909091 = 105,000.00\text{ EUR}$$
- **EUR Debt Liability**:
  $$A_{liability} = 100,000.00 \times (1 + 0.02) = 102,000.00\text{ EUR}$$
- **Pure Net Gain**:
  $$\text{Net Profit} = 105,000.00 - 102,000.00 = +3,000.00\text{ EUR}$$
- **Decomposition**:
  $$\text{Pure FX Gain} = \$115,500.00 \times (0.90909091 - 0.90909091) = 0.00\text{ EUR}$$
  $$\text{Asset Yield} = \$110,000.00 \times 0.05 \times 0.90909091 = +5,000.00\text{ EUR}$$
  $$\text{Financing Cost} = -2,000.00\text{ EUR}$$
  $$\text{Reconciliation}: +5,000.00 - 2,000.00 = +3,000.00\text{ EUR}$$

### Example 2: USD/EUR Reciprocal Trade (Borrow USD, Invest EUR)
- **Borrowing Currency $A$**: USD
- **Investment Currency $B$**: EUR
- **Borrowed Capital $L_A$**: $\$100,000.00\text{ USD}$
- **Market Quote (Frankfurter)**: EUR/USD $= 1.1000$ (i.e. $1.1000\text{ USD per 1 EUR}$)
- **Canonical Conversion**:
  $$A = \text{USD}, B = \text{EUR} \implies rate_{A/B} = 1.1000\text{ USD per 1 EUR}$$
- **Capital Conversion**:
  $$\text{EUR Invested} = \frac{\$100,000.00}{1.1000} = 90,909.0909\text{ EUR}$$
- **Tenor**: 360 days (1 year)
- **Interest Rates**: USD borrowing rate $r_A = 5.0\%$; EUR investment rate $r_B = 2.0\%$
- **Asset Growth in EUR**:
  $$B_{final} = 90,909.0909 \times (1 + 0.02) = 92,727.2727\text{ EUR}$$
- **Exit Market Quote**: EUR/USD $= 1.1000$
- **Repatriated USD Proceeds**:
  $$A_{gross} = 92,727.2727\text{ EUR} \times 1.1000 = \$102,000.00\text{ USD}$$
- **USD Debt Liability**:
  $$A_{liability} = \$100,000.00 \times (1 + 0.05) = \$105,000.00\text{ USD}$$
- **Pure Net Gain**:
  $$\text{Net Profit} = \$102,000.00 - \$105,000.00 = -\$3,000.00\text{ USD}$$
- **Decomposition**:
  $$\text{Pure FX Gain} = \$0.00$$
  $$\text{Asset Yield} = 90,909.0909 \times 0.02 \times 1.1000 = +\$2,000.00\text{ USD}$$
  $$\text{Financing Cost} = -\$5,000.00\text{ USD}$$
  $$\text{Reconciliation}: +\$2,000.00 - \$5,000.00 = -\$3,000.00\text{ USD}$$

### Example 3: Two-Way Quote with Asymmetric Market Spread
- **Borrowing Currency $A$**: EUR
- **Investment Currency $B$**: USD
- **Market Quote**: EUR/USD Bid $= 1.0998$, Ask $= 1.1002$ (USD per EUR)
- **Canonical Conversion to EUR per USD**:
  $$Bid_{A/B} = \frac{1.0}{Ask_{market}} = \frac{1.0}{1.1002} = 0.90892565\text{ EUR/USD}$$
  $$Ask_{A/B} = \frac{1.0}{Bid_{market}} = \frac{1.0}{1.0998} = 0.90925623\text{ EUR/USD}$$
- **Spread Check**:
  $$Ask_{A/B} - Bid_{A/B} = 0.90925623 - 0.90892565 = 0.00033058 > 0$$
- **Entry Execution**: Buy USD at $Ask_{A/B} = 0.90925623$
  $$\text{USD Acquired} = \frac{100,000\text{ EUR}}{0.90925623} = \$109,980.00$$
- **Immediate Exit Liquidation**: Sell USD at $Bid_{A/B} = 0.90892565$
  $$\text{EUR Received} = \$109,980.00 \times 0.90892565 = 99,963.64\text{ EUR}$$
- **Round-Trip Spread Cost**:
  $$100,000.00 - 99,963.64 = 36.36\text{ EUR}$$
  $$\text{Spread in bps} = \frac{36.36}{100,000} \times 10,000 = 3.636\text{ bps}$$
  Matching the raw market spread $(1.1002 - 1.0998) / 1.1000 = 3.636\text{ bps}$ exactly.

---

## 7. Bid/Ask Execution Direction Proofs

For any trade, market frictions must always work against the trader:

| Phase | Strategy Action | Canonical Market Side Taken | Execution Rate Applied | Spread Cost Paid |
| :--- | :--- | :--- | :--- | :--- |
| **Entry** | Buy Currency $B$ using $A$ | Must lift the market offer | $Ask_{A/B} = Mid \times (1 + \frac{\text{half-spread}}{10,000})$ | $L_A \times \frac{\text{half-spread}}{10,000}$ |
| **Exit** | Sell Currency $B$ to receive $A$ | Must hit the market bid | $Bid_{A/B} = Mid \times (1 - \frac{\text{half-spread}}{10,000})$ | $A_{gross} \times \frac{\text{half-spread}}{10,000}$ |

### Zero Double-Counting Guarantee
The execution engine implements two mutually exclusive spread accounting modes:
- **Mode A (`use_observed_spread=True`)**: If genuine market bid and ask quotes exist on the observation, execution uses `observed_ask` on entry and `observed_bid` on exit. Parameter `bid_ask_spread_bps` is forced to $0.0$, ensuring observed market spreads are paid while synthetic spreads are zero.
- **Mode B (`use_observed_spread=False` or reference rate proxy)**: If only a reference price exists, synthetic spread is evaluated using `bid_ask_spread_bps / 2.0`. Parameter `observed_spread_cost_a` is recorded as $0.0$.
In both modes:
$$\text{Observed Spread Cost} \times \text{Modelled Spread Cost} = 0.0$$

---

## 8. Quote Freshness & One-Sided Quote Requirements

To prevent backtesting against stale or non-executable quotes:

1. **Observation Timestamp Requirement**:
   For any real (non-synthetic) market observation claiming `EXECUTABLE_TWO_WAY_QUOTE`, `BID_QUOTE`, or `ASK_QUOTE`, the observation must contain an explicit, verified `observation_timestamp` satisfying:
   $$\text{observation\_timestamp} \le \text{execution\_timestamp}$$
2. **Freshness Bound**:
   $$\text{execution\_timestamp} - \text{observation\_timestamp} \le \text{max\_quote\_age\_minutes}$$
   Quotes older than the threshold (default: 1440 minutes / 24 hours) are discarded as stale, and trade attempts are registered in `rejections`.
3. **One-Sided Quote Assembly**:
   If separate `BID_QUOTE` and `ASK_QUOTE` observations are provided:
   - They may only be combined into a two-way quote if:
     $$|\text{timestamp}_{bid} - \text{timestamp}_{ask}| \le \text{max\_one\_sided\_quote\_time\_diff\_seconds}\quad (\text{default: } 60\text{ s})$$
   - If $|\Delta t| > 60\text{ s}$, quote assembly is refused.
4. **Standalone One-Sided Quotes**:
   - A standalone `ASK_QUOTE` can only execute trade entries (buying $B$).
   - A standalone `BID_QUOTE` can only execute trade exits (selling $B$).
   - A one-sided quote can **never** execute an entire round-trip trade on its own.

---

## 9. Spread and Slippage Accounting

All transaction costs are recorded using double-entry accounting with exact return attribution:

$$\text{Total Frictions Drag} = \text{Observed Spread Drag} + \text{Modelled Spread Drag} + \text{Slippage Drag} + \text{Fee Drag}$$

### Mathematical Attribution Decomposition:
$$\text{Pure Gross Profit}_A = \text{Pure FX Translation Gain}_A + \text{Investment Asset Yield}_A$$
$$\text{Net Profit}_A = \text{Pure Gross Profit}_A - \text{Financing Cost}_A - \text{Total Frictions}_A + \text{Cash Interest}_A$$
$$\text{Residual} = |\text{Net Profit}_A - (\text{Pure Gross Gain} - \text{Financing} - \text{Frictions} + \text{Cash Interest})| \le 10^{-10}\text{ EUR}$$

---

## 10. Historical Results Before and After Correction

The 2020–2024 historical experiment was executed across the 6 required configurations on `sqlite:///data/processed/gmdb.db`:

### Comprehensive Configuration Matrix:
| Configuration | Strategy Status | Trades | Total Return | Pure FX Return | Asset Yield | Financing Cost | Spread Drag | Slippage | Sharpe | Alpha |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Config 1 (Strict Verified PIT)** | `RESEARCH_PROXY` | 0 | **+0.00%** | +0.00% | +0.00% | -0.00% | -0.00% | -0.00% | N/A | N/A |
| **Config 2 (Estimated Ref-Rate Proxy)** | `RESEARCH_PROXY` | 60 | **+2.91%** | **-6.71%** | **+6.27%** | **-2.92%** | **-0.60%** | **-0.30%** | **-0.04** | **-0.93%** |
| **Config 3 (Strict Executable Quotes)** | `UNEXECUTABLE` | 0 | **+0.00%** | +0.00% | +0.00% | -0.00% | -0.00% | -0.00% | N/A | +0.00% |
| **Config 4 (Currency-Matched Benchmark)**| `RESEARCH_PROXY` | 60 | **+2.91%** | **-6.71%** | **+6.27%** | **-2.92%** | **-0.60%** | **-0.30%** | **-0.04** | **-0.93%** |
| **Config 5 (Mismatched Benchmark USD)** | `RESEARCH_PROXY` | 60 | **+2.91%** | **-6.71%** | **+6.27%** | **-2.92%** | **-0.60%** | **-0.30%** | 0.36 | **N/A** |
| **Config 6 (Covered Carry Rejection)** | `UNEXECUTABLE` | 0 | **+0.00%** | +0.00% | +0.00% | -0.00% | -0.00% | -0.00% | N/A | N/A |

### Historical Progression Across Milestones (Configuration 2 Baseline):
| Milestone | Reported Return | Trades | Pure FX Return | Asset Yield | Win Rate | Profit Factor | Status | Cause of Difference |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 3.2** | +13.27% | 60 | N/A | N/A | 55.0% | 1.34 | `EXECUTABLE` (Naive) | Daily date lookup, naive fees, unnormalized FX |
| **Phase 3.2.1** | +13.88% | 60 | N/A | N/A | 53.3% | 1.28 | `RESEARCH_PROXY` | Economic rate roles, unencumbered cash accrued |
| **Phase 3.2.2** | +14.06% | 60 | N/A | N/A | 53.3% | 1.29 | `RESEARCH_PROXY` | Intraday timestamp awareness, publication lags |
| **Phase 3.2.2.1** | +14.06% | 60 | N/A | N/A | 53.3% | 1.29 | `RESEARCH_PROXY` | SQLite round-trip metadata preservation |
| **Phase 3.2.2.2** | +14.08% | 60 | N/A | N/A | 53.3% | 1.29 | `RESEARCH_PROXY` | TARGET2/Fed settlement calendar, weekend shifts |
| **Phase 3.2.2.3** (Current) | **+2.91%** | 60 | **-6.71%** | **+6.27%** | **46.7%** | **0.83** | `RESEARCH_PROXY` | **Corrected canonical FX convention ($rate_{A/B}$)** |

### Mathematical Explanation of the Return Shift (+14.08% $\to$ +2.91%):
The entire difference of $-11.17\%$ is explained by the correction of the FX exchange-rate convention:
1. **The Inversion Error**: Previously, $100,000\text{ EUR}$ was converted to USD by dividing by $1.1000$ ($\$90,909.09$) instead of multiplying by $1.1000$ ($\$110,000.00$). When USD appreciated against EUR, the inverted conversion magnified profits during dollar pullbacks and suppressed true dollar cycle drawdowns.
2. **True Spot Movement**: Over the 2020–2024 period, the unhedged EUR/USD carry trade lost **$-6,714.52\text{ EUR}$** ($-6.71\%$) in pure FX movement.
3. **True Gross Profit**: While USD yield contributed $+6,270.59\text{ EUR}$, it did not cover the spot FX losses, leading to a negative gross trade return ($-443.92\text{ EUR}$).
4. **Net Strategy Loss on Deployed Capital**: After debt financing costs ($-2,922.32\text{ EUR}$) and execution fees ($-1,499.54\text{ EUR}$), the active carry trade generated a net loss of $-4,865.78\text{ EUR}$ on deployed capital.
5. **Cash Yield Offset**: The positive total return of $+2,906.92\text{ EUR}$ (+2.91%) was generated exclusively by unallocated cash balances earning 1.5% annual deposit interest ($+7,772.70\text{ EUR}$).
6. **Benchmark Underperformance**: Against a 1.5% EUR cash deposit benchmark (+7.73%), the carry strategy underperformed by **$-4.82\%$** cumulative (**$-0.93\%$** annualized alpha), with a Sharpe ratio of **$-0.04$**.

---

## 11. Benchmark and Sharpe Methodology

### 1. Currency Matching Rule
To prevent comparing apples to oranges, benchmark yields must match the strategy's liability borrowing currency ($A$):
- In Configuration 4: Benchmark currency is EUR, matching EUR liabilities. Annualized benchmark return is $+1.50\%$, and alpha is validly calculated as $-0.93\%$.
- In Configuration 5: Benchmark currency is USD (3-month US Treasury yield `DGS3MO`). The engine rejects this comparison, recording:
  ```
  BENCHMARK UNAVAILABLE: Mismatched benchmark currency 'USD' against strategy borrowing currency 'EUR'.
  ```
  `benchmark_annualized_return` and `alpha` are set to `None`.

### 2. Bounded Benchmark Staleness
Forward filling for historical risk-free or deposit rate series is capped by `max_benchmark_stale_days` (default: 5 calendar days). If a benchmark series has a missing data gap exceeding 5 days, the benchmark is marked `UNAVAILABLE` and alpha is set to `None`.

### 3. Risk-Free Rate Alignment for Sharpe Ratio
The annualized Sharpe ratio is evaluated strictly against the borrowing currency's risk-free / cash reference series, not by substituting commercial borrowing liability rates. In Configuration 2, the annual Sharpe ratio is $-0.04$, reflecting negative excess return over risk-free EUR cash.

---

## 12. Strategy Executability Assessment

Following the three-tier classification architecture:

1. **`StrategyExecutabilityStatus.EXECUTABLE_VALIDATED`**:
   Requires verified intraday publication timestamps, genuine two-way execution quotes with observable spreads, and commercial borrowing/deposit rates. Currently **0** configurations achieve this status because ECB reference rates are end-of-day fixings rather than tradable institutional streaming quotes.
2. **`StrategyExecutabilityStatus.RESEARCH_PROXY`**:
   Assigned to Configuration 2, Configuration 4, and Configuration 5. Accurately simulates retrospective economic relationships using daily reference rates and estimated publication lags, but is transparently declared non-executable in production.
3. **`StrategyExecutabilityStatus.UNEXECUTABLE`**:
   Assigned to Configuration 3 (when daily reference rates are rejected as execution quotes) and Configuration 6 (covered carry trade, because genuine forward exchange quotes do not exist in the dataset).

---

## 13. Remaining Limitations

1. **Intraday Tick Execution**: Historical observations in the GMDB dataset are daily reference rates (ECB fixing at 16:00 CET) rather than millisecond tick-by-tick order book feeds.
2. **Institutional Forward Swaps**: Covered carry trading requires genuine institutional FX forward point curves (e.g. 1M, 3M forward swap points from EBS/Reuters), which are not available in free open-access public repositories.
3. **Dynamic Margin & Haircuts**: Sizing currently models fixed capital allocation without dynamic intraday variation margin calls.

---

## 14. Test Results

The comprehensive test suite was expanded with 15 new mathematical and execution audit tests in `tests/test_audit_phase_3_2_2_3.py`.

### Full Test Suite Execution:
```bash
uv run pytest
```
```
collected 213 items

tests\test_adapters.py ................                                  [  7%]
tests\test_audit_benchmarks_provenance.py ....                           [  9%]
tests\test_audit_metrics_risk.py .........                               [ 13%]
tests\test_audit_phase_3_2_1.py .........                                [ 17%]
tests\test_audit_phase_3_2_2.py ............                             [ 23%]
tests\test_audit_phase_3_2_2_1.py ............                           [ 29%]
tests\test_audit_phase_3_2_2_2.py ................                       [ 36%]
tests\test_audit_phase_3_2_2_3.py ...............                        [ 43%]
tests\test_audit_point_in_time.py ...                                    [ 45%]
tests\test_backtest_engine_integration.py ..                             [ 46%]
tests\test_backtest_execution_financing.py ......                        [ 48%]
tests\test_backtest_metrics_benchmarks.py ...                            [ 50%]
tests\test_backtest_point_in_time.py .....                               [ 52%]
tests\test_backtest_portfolio.py ....                                    [ 54%]
tests\test_backtest_strategies.py ......                                 [ 57%]
tests\test_backtest_walk_forward.py ...                                  [ 58%]
tests\test_carry_trade.py .........                                      [ 62%]
tests\test_coverage.py ....                                              [ 64%]
tests\test_currency.py ............                                      [ 70%]
tests\test_ingest.py ....                                                [ 72%]
tests\test_interest.py ............                                      [ 77%]
tests\test_real_market_validation.py ......                              [ 80%]
tests\test_repository.py ............                                    [ 86%]
tests\test_risk.py .............                                         [ 92%]
tests\test_schemas_quality.py ................                           [100%]

============================ 213 passed in 56.34s =============================
```
- **Total Tests Passing**: **213**
- **Test Failures**: **0**
- **Coverage**: Currency inversion invariants, reciprocal quotes, crossed quote rejection, one-sided quote assembly, quote timestamp enforcement, mode A/B spread isolation, double-entry P&L reconciliation, bounded benchmark staleness, and benchmark currency validation.

---

## 15. Reproduction Instructions

To reproduce the complete historical results from scratch:

1. **Verify Test Suite**:
   ```bash
   uv run pytest
   ```
2. **Execute the 6-Configuration Reproduction Experiment**:
   ```bash
   uv run python examples/reproduce_phase_3_2_2_3.py
   ```
3. **Inspect Generated JSON and Markdown Artifacts**:
   - Machine-readable result objects: `data/results/phase_3_2_2_3/config_*.json`
   - Detailed audit report: `data/results/phase_3_2_2_3/config_2_audit_report.md`
   - Byte-stable archive manifest: `data/manifest.json`

---

## 16. Verification Sign-Off

- **Baseline Commit**: `ee298cc2b5a90a105926cafc9491211a3f992955`
- **Audit Verification Status**: Complete and fully verified.
- **Quantitative Result Integrity**: Every transaction, quote conversion, cash flow, interest accrual, and fee is double-entry reconciled with an absolute residual $\le 10^{-10}\text{ EUR}$.
- **Methodological Conclusion**: The historical +14.08% result from Phase 3.2.2.2 was mathematically refuted and traced to legacy currency conversion inversion. The corrected 2020–2024 unhedged carry trade return is **+2.91%**, which underperformed risk-free cash holding by **-4.82%** cumulative (**-0.93%** annualized alpha) with a negative Sharpe ratio of **-0.04**.
