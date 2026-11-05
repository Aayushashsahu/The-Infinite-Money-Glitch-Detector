# The Infinite Money Glitch Detector

AI-powered macro-financial research and quantitative strategy analysis
platform. It investigates whether apparent cross-country arbitrage
opportunities (inflation gaps, interest-rate differentials, exchange-rate
moves) survive financing costs, currency fluctuations, transaction fees
and risk adjustments — and is explicitly designed to **reject false
opportunities**, not to assume profit.

**Guiding principle: Mathematics first. Data second. Prediction third. AI last.**

## Status: Phase 3.2.1 — Quantitative Integrity & Executability Audit ✅

- **Phase 1 (Mathematical Foundation):** Complete (46 tests).
- **Phase 2 (Economic Data Infrastructure):** Complete (98 tests).
- **Phase 3 (Historical Backtesting Engine):** Complete (127 tests).
- **Phase 3.1 (Methodology & Benchmark Audit):** Complete (141 tests).
- **Phase 3.2 (Real Market Data Validation 2020-2024):** Complete (149 tests).
- **Phase 3.2.1 (Quantitative Integrity & PIT Audit):** Complete (158 passed tests).

See [`PHASE_3_2_1_QUANTITATIVE_INTEGRITY_AUDIT.md`](PHASE_3_2_1_QUANTITATIVE_INTEGRITY_AUDIT.md) for the complete quantitative audit, exact cash flow ledger proofs, and regime analysis.
See [`PHASE_3_2_REAL_DATA_VALIDATION.md`](PHASE_3_2_REAL_DATA_VALIDATION.md) for the preserved historical baseline.

### What Phase 2 guarantees

- Every observation keeps its **observation date** and its **publication
  date** (stored `NULL` when a provider does not publish one — never
  invented), plus its revision number.
- Re-ingestion is idempotent: identical replays are counted as
  duplicates, changed values become new revisions, history is preserved.
- Provider payloads are archived verbatim with a content hash in
  `raw_record`, so any stored number can be traced back to its source
  response.
- Synthetic rows are permanently marked (`is_synthetic`) and excluded
  from analytical reads by default.
- `point_in_time(as_of=...)` drops rows not yet published, defending
  backtests from look-ahead bias.

## The core formula

Cross-currency carry trade. Borrow `L` in currency A, invest it in
currency B at expected return `rB`, repay at rate `rA`, A per B:

```
Profit_A = L * [ (1 + rB) * (X1 / X0) - (1 + rA) ] - C

L   principal borrowed in A
rA  borrowing rate (annual)
rB  investment return in B (annual, an assumption — never a forecast)
X0  initial exchange rate, units of A per unit of B
X1  final exchange rate,  units of A per unit of B
C   transaction and other costs, in A
```

Break-even exchange rate: `X1* = X0 * ( fA + C/L ) / fB`, where `fA`/`fB`
are the effective growth factors of `rA`/`rB` over the holding period.
Net profit is monotone increasing in `X1`, so the strategy loses money
whenever `X1 < X1*`.

### Milestone scenario (verified by hand and by test)

| Step | Value |
|---|---|
| Borrow 100,000 A at 12 % | repayment 112,000 A |
| Convert at X0 = 1 A/B | 100,000 B |
| Grow at 5 % | **105,000 B** |
| Convert back at X1 = 1.15 A/B | **120,750 A** |
| Transaction costs | **2,000 A** |
| **Net profit** | **+6,750 A** (ROI 6.75 %) |

`tests/test_carry_trade.py::test_milestone_scenario_end_to_end` is the
gate: it fails, we do not move forward.

## Conventions (fixed, documented, never implicit)

- **Exchange rate**: always *units of A per unit of B*. Converting A→B
  divides by X; converting B→A multiplies by X. See
  `src/core/currency.py`. Never invert a rate by hand — use
  `inverse_rate`.
- **Rates**: annual, as fractions (`0.12` = 12 %). Period rates are
  derived explicitly, with a selectable convention:
  - *simple*: `r_period = r_annual * t` (linear growth `1 + r t`)
  - *compound*: `(1 + r)**t` (geometric growth)
  Conversion happens in `src/core/interest.py`.
- **Interest convention**: an explicit field on every calculation input
  (`schemas.strategy.InterestConvention`). It is never guessed.
- **Missing data**: raising errors, never fabricating values
  (`src/models/risk.py` refuses NaN/inf input).
- **Forecasts vs baselines**: PPP output is labeled a theoretical
  long-run *baseline*, not a forecast. Simulations-like outputs (the
  sensitivity grid) are *hypothetical scenarios*, not forecasts.

## Project structure

```
src/
├── core/            # primitive math: currency conversion, interest, unit conversions
│   ├── currency.py
│   ├── interest.py
│   └── conversions.py
├── models/          # strategy & metric engines (Pydantic in/out)
│   ├── carry_trade.py
│   ├── ppp.py
│   └── risk.py
├── simulation/
│   └── sensitivity.py   # deterministic scenario grids
├── schemas/
│   └── strategy.py      # shared input/output contracts + vocabulary
├── data/                # Phase 2: economic data infrastructure
│   ├── adapters/        # world_bank, frankfurter, imf, policy_rates (ECB, FRED)
│   ├── db/              # engine + ORM models (9 tables)
│   ├── schemas.py       # observation / fetch contracts
│   ├── quality.py       # batch validation (flags, never deletes)
│   ├── coverage.py      # series coverage + sufficiency
│   ├── ingest.py        # orchestration + run accounting
│   └── repository.py    # idempotent persistence, point-in-time reads
└── main.py              # demo runner for the milestone scenario
alembic/                 # schema migration (d87fb89eff94)
tests/                   # pytest suite, hand-verified expected values
data/raw/, data/processed/   # raw payload archive / SQLite demo store
scripts/example_ingestion.py # offline-first demo, real fetches optional
notebooks/, docs/
.env.example             # DATABASE_URL, FRED_API_KEY (optional)
```

### Architecture decision (enforced)

The mathematical engine is **independent of presentation and AI**.
`calculate_carry_trade` has zero knowledge of dashboards, databases,
HTTP or LLMs. A backtester, an API endpoint, a Streamlit page and the
future AI assistant must all call the exact same function — so flashy
visuals can never drift from audited arithmetic.

## Setup and usage

```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash; `. .venv/bin/activate` on POSIX
pip install -e ".[dev]"
pytest                            # run the full suite
python src/main.py                # milestone scenario + sensitivity grid
python scripts/example_ingestion.py   # Phase 2 demo: synthetic + real keyless ingests

alembic upgrade head              # apply the Phase 2 schema to DATABASE_URL
```

## What each module does

| Module | Contents |
|---|---|
| `core.currency` | ISO 4217-style validation, conversions under the fixed rate convention, `inverse_rate` |
| `core.interest` | `growth_factor`, `period_rate_from_annual`, `loan_repayment`, `interest_paid`, simple/compound |
| `core.conversions` | percent/fraction, `annualized_return` (simple & compound), `rate_change` |
| `models.carry_trade` | `CarryTradeInput/Output`, `calculate_carry_trade`, `TransactionCosts` (fixed + per-leg bps spread) |
| `models.ppp` | relative-PPP baseline: expected depreciation of A ≈ πA − πB |
| `models.risk` | historical volatility, max drawdown, VaR (empirical, lower method), CVaR, Sharpe, break-even probability |
| `simulation.sensitivity` | exchange-rate scenario grid through the real engine |

## Known limitations (Phase 1)

1. `rB` is an assumed *expected* return supplied by the caller; nothing
   here forecasts returns.
2. PPP is a long-run baseline; it demonstrably fails as a short-term
   exchange-rate forecast.
3. Risk metrics are sample statistics of the supplied series: VaR/CVaR
   know nothing beyond the observed tail, and short samples are unstable.
4. Sharpe requires a defensible risk-free benchmark — the caller must
   supply one; no default benchmark is invented.
5. Transaction costs are a simple flat + bps model; realistic costs
   (banned liquidity, capital controls) come with real data.
6. Phase 1 code is exercised only on synthetic, hand-verified inputs;
   real-data backtesting arrives in Phase 3.

## Roadmap (do not skip ahead)

- **Phase 1** ✅ — deterministic math + tests
- **Phase 2** ✅ — data engineering (World Bank / IMF / central banks / FX adapters, raw vs processed stores, no silent forward-fills, look-ahead-bias prevention)
- **Phase 3** ✅ — backtesting engine (walk-forward, out-of-sample, benchmarks)
- **Phase 3.1** ✅ — quantitative validation audit (comparable benchmarks, provenance reports, risk metric audit)
- **Phase 3.2** ✅ — real market data validation (2020-2024 genuine data, 2 macro regimes, NIRP vs tightening)
- **Phase 3.2.1** ✅ — quantitative integrity, point-in-time & executability audit (timestamp firewall, double-entry ledger, weekend rollover)
- **Phase 4** — Monte Carlo simulation (historical bootstrap, stress scenarios, fat tails)
- **Phase 5** — Streamlit/Plotly dashboard (reads, never recomputes, the engine)
- **Phase 6** — AI assistant (explains outputs; never computes numbers itself)
