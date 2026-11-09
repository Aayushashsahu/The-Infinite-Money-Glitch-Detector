# The Infinite Money Glitch Detector

[![CI](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/actions/workflows/ci.yml/badge.svg)](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/actions/workflows/ci.yml)
[![Release](https://img.shields.io/badge/release-v1.0.0-blue.svg)](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/releases/tag/v1.0.0)
[![Python Versions](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-1%2C094%20passed-success.svg)](tests/)
[![Status](https://img.shields.io/badge/status-production--ready-green.svg)](docs/PHASE_5_4_FINAL_AUDIT_REPORT.md)

An institutional quantitative research and macro-financial analytics platform designed to rigorously evaluate cross-currency arbitrage opportunities, carry-trade mechanics, and multi-factor risk distributions.

**Repository:** [Aayushashsahu/The-Infinite-Money-Glitch-Detector](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector)<br>
**Latest Release:** [v1.0.0](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/releases/tag/v1.0.0)<br>
**System Milestone:** Phase 5 — Interactive Research Dashboard (Complete & Audited)

---

## 1. Overview

The platform investigates a classic macroeconomic question in international finance: **Does an apparent cross-currency arbitrage opportunity survive real-world market frictions?**

Specifically, the core research investigates borrowing in a low-yielding currency (EUR), converting at spot rates to a higher-yielding currency (USD), investing in short-term sovereign paper or money-market deposits, and converting back at maturity:

$$\text{Profit}_{\text{EUR}} = L \cdot \left[ (1 + r_{\text{USD}}) \cdot \frac{S_{t_1}}{S_{t_0}} - (1 + r_{\text{EUR}}) \right] - C_{\text{transaction}}$$

Where:
- $L$ is the borrowed principal in EUR.
- $r_{\text{USD}}$ is the US investment interest rate over the tenor.
- $r_{\text{EUR}}$ is the Euro borrowing rate over the tenor.
- $S_{t_0}, S_{t_1}$ are the spot EUR/USD exchange rates at entry and exit.
- $C_{\text{transaction}}$ accounts for bid/ask spreads, borrowing spreads, and transaction costs.

### Research Engine vs. Trading System
The platform is an **empirical validation and falsification engine**, not an execution algorithm or trade broker:
- It is explicitly designed to **reject false arbitrage**, not assume profit.
- It incorporates strict point-in-time publication timestamps to eliminate look-ahead bias.
- It models contractual financing accrual over weekends, holidays, and settlement conventions.
- When market data is incomplete (such as institutional forward FX bid/ask quotes in public tiers), it marks strategies as **`UNEXECUTABLE`** rather than fabricating synthetic quotes.

---

## 2. Research Philosophy

> **"Mathematics first. Data second. Prediction third. AI last."**

1. **Mathematics First:** Every financial metric, cash flow transition, and risk statistic is defined with closed-form mathematical rigor and reconciled via double-entry accounting down to floating-point machine precision ($|r| \le 3.09 \times 10^{-11}$).
2. **Data Second:** Strict Point-in-Time (PIT) isolation. Observations are indexed by both their historical observation date and their actual public release timestamp. Revisions are versioned; future data is permanently blocked.
3. **Prediction Third:** Multi-factor stochastic models (Student-$t$ with MLE degrees of freedom, GJR-GARCH asymmetric volatility, Block Bootstrap) and deterministic stress scenarios are evaluated only after the historical baseline is established and verified.
4. **AI Last:** AI and Large Language Models are reserved strictly as an interpretive explanation layer. The analytical and calculation engines are deterministic Python and C-extensions; AI never calculates numbers or invents data.

---

## 3. Key Capabilities

- **Point-in-Time Economic Ingestion:** Multi-source ETL pipelines covering the European Central Bank (ECB SDMX), Federal Reserve (FRED H.15), World Bank, and market FX providers, preserving raw payloads with SHA-256 content hashes.
- **Contractual Settlement Calendars:** Full modeling of TARGET2 and US Federal Reserve holiday calendars, 3-day weekend funding accruals, holiday carry, and discrete 30-day tenor maturities.
- **Double-Entry Cash Flow Accounting:** Exhaustive trade-by-trade cash flow ledger reconciling loan principal, spot FX conversions, interest accrual, bid/ask friction, and repayment.
- **Multi-Factor Stochastic Laboratory:** 6 Monte Carlo simulation models calibrated over empirical 4-factor panels (EUR/USD, US 3M Treasury, EUR Deposit Rate, US Inflation).
- **Non-Linear Stress Testing:** 19 deterministic macro shock scenarios (e.g., Global Financial Crisis replay, 2022 Fed hiking cycle, stagflation, dollar collapse) with exact cash flow reconciliation.
- **Correlation Decoupling Analysis:** Paired Common Random Numbers experiment testing portfolio resilience under total factor correlation breakdown ($\mathbf{R}_{\text{stressed}} = \mathbf{I}$).
- **Out-of-Sample Holdout Diagnostics:** Evaluation of 2024 empirical factor distributions against the 2020–2023 calibration sample, featuring Kolmogorov-Smirnov test diagnostics.
- **Cryptographic Artifact Registry:** 23 authoritative JSON research artifacts cryptographically locked with SHA-256 digests and verified on load.
- **Strictly Read-Only Presentation Layer:** Six-page interactive Streamlit and Plotly dashboard with AST import guards and read-only SQLite enforcement (`?mode=ro` with `PRAGMA query_only = ON`).

---

## 4. Research Dashboard Preview

The interactive dashboard provides researchers and risk officers with full visibility into the precomputed, cryptographically verified research outputs.

### Landing Page & Architecture Overview
Central navigation hub displaying system topology, environmental invariants, data pipeline states, and verification summaries.

![Main Landing](docs/screenshots/main_landing_desktop.png)

---

### Page 1: Research Overview
Executive synthesis contrasting historical backtest performance against forward stochastic distributions, complete with dynamic KPI cards and explicit disclosures.

![Research Overview](docs/screenshots/page_1_research_overview_desktop.png)

---

### Page 2: Carry Trade Performance
Comprehensive deep dive into the historical backtest (Config 2 Estimated Schedule), featuring a mathematically exact double-entry P&L attribution waterfall chart and strategy vs. benchmark performance comparisons.

![Carry Trade Performance](docs/screenshots/page_2_carry_trade_performance_desktop.png)

---

### Page 3: Market Data & Provenance
Complete transparency into all 8,908 historical observations, point-in-time release lag policies, interactive SQLite series explorer, and settlement calendar anomaly validation.

![Market Data & Provenance](docs/screenshots/page_3_market_data_provenance_desktop.png)

---

### Page 4: Monte Carlo Laboratory
Stochastic simulation engine comparing 6 distribution models (Gaussian, Student-$t$, GJR-GARCH, AR(1)-GJR-GARCH, Historical Bootstrap, Block Bootstrap) with representative path trajectories and sample-size convergence diagnostics.

![Monte Carlo Laboratory](docs/screenshots/page_4_monte_carlo_laboratory_desktop.png)

---

### Page 5: Risk & Stress Testing
Interactive stress testing suite evaluating 19 macro scenarios, tornado sensitivity ranking, funding reset shock analysis (+0 to +500 bps), and correlation decoupling diagnostics.

![Risk & Stress Testing](docs/screenshots/page_5_risk_stress_testing_desktop.png)

---

### Page 6: Holdout Diagnostics
Out-of-sample factor validation for calendar year 2024, Kolmogorov-Smirnov distribution tests, factor correlation shift tracking, and institutional disclosure of the unavailable portfolio holdout state.

![Holdout Diagnostics](docs/screenshots/page_6_holdout_diagnostics_desktop.png)

---

## 5. Summary of Research Results

All figures below are extracted directly from authoritative, cryptographically verified research artifacts and match dashboard displays within $\le 10^{-9}$ precision.

### Historical Carry Trade Backtest (Config 2 — Estimated Schedule Baseline)
- **Evaluation Period:** 2020-01-01 to 2024-12-31 (1,236 daily market transitions).
- **Initial Capital:** €100,000.00
- **Cumulative Net Profit:** +€2,890.22 (+2.89% total return)
- **Annualized Return:** +0.57% p.a.
- **Benchmark (EUR Fixed Deposit):** +1.50% p.a. (+7.73% cumulative)
- **Annualized Alpha:** -0.93% (-92.9 basis points vs. matched benchmark)
- **Sharpe Ratio:** -0.039 (negative risk-adjusted excess return)
- **Maximum Drawdown:** -3.52%
- **Trade Execution Audit:** 29 executed trades (13 winning, 16 losing), 31 rejected trades (due to negative interest differential or excessive spread).
- **P&L Attribution Breakdown:**
  - Gross Interest Differential: +€14,812.45
  - Currency Spot Translation Loss: -€10,985.30
  - Bid/Ask Spread Friction: -€936.93
  - Net Residual Accounting Error: $\le 3.09 \times 10^{-11}$

### Alternative Configurations Matrix (Phase 3 Audit)

| Config | Configuration Name | Executed Trades | Total Return | Sharpe Ratio | Strategy Status & Audit Outcome |
| :---: | :--- | :---: | :---: | :---: | :--- |
| **1** | Strict PIT Baseline | 0 | 0.00% | N/A | Strict intraday quotes unavailable; zero trades executed. |
| **2** | **Estimated Schedule (Baseline)** | **29** | **+2.89%** | **-0.039** | **Authoritative baseline; underperforms risk-free benchmark.** |
| **3** | Strict Quotes Isolation | 0 | 0.00% | N/A | Forward bid/ask quotes missing in public tier; zero execution. |
| **4** | Matched Benchmark | 29 | +2.89% | -0.039 | Alpha: -0.93% vs. Matched EUR Fixed Deposit Benchmark. |
| **5** | Mismatched Benchmark | 29 | +2.89% | -0.039 | Alpha: -1.13% vs. Unhedged USD Treasury Benchmark (+8.44%). |
| **6** | Covered Rejection | 0 | 0.00% | N/A | **`UNEXECUTABLE`**: Forward quotes missing; covered arbitrage rejected. |

### Monte Carlo Stochastic Simulation Outcomes ($N=1,000$ paths, 252 days)

| Distribution Model | Median Return | 95% CVaR (Expected Shortfall) | Loss Probability | Model Characterization |
| :--- | :---: | :---: | :---: | :--- |
| **Multivariate Gaussian** | +1.75% | -5.97% | 27.8% | Thin-tailed benchmark; underestimates tail risk. |
| **Student-$t$ ($\nu = 7.74$)** | +1.74% | -6.18% | 28.1% | Heavy-tailed; profile MLE degrees of freedom. |
| **GJR-GARCH(1,1)** | +1.73% | -6.21% | 27.9% | Asymmetric leverage volatility clustering. |
| **AR(1)-GJR-GARCH** | +1.72% | -6.25% | 28.0% | Conditional mean autocorrelation + volatility clustering. |
| **Historical Bootstrap** | +1.71% | -5.94% | 27.7% | Non-parametric empirical return resampling. |
| **Block Bootstrap (Block=5)** | +1.72% | -5.96% | 27.8% | Preserves short-horizon serial correlation. |

---

## 6. Data Integrity and Security Architecture

```
                    ┌──────────────────────────────────────────┐
                    │       Authoritative Data Sources         │
                    │   ECB SDMX  •  FRED H.15  •  World Bank  │
                    └─────────────────────┬────────────────────┘
                                          │ Raw Payloads + SHA-256
                                          ▼
                    ┌──────────────────────────────────────────┐
                    │    Strict Point-in-Time Data Store       │
                    │       SQLite Database (gmdb.db)          │
                    │   SHA-256: 7913ae5ced269d476a07...       │
                    └─────────────────────┬────────────────────┘
                                          │ Immutable Read-Only Connection
                                          ▼ (?mode=ro & PRAGMA query_only=ON)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Presentation & UI Layer (Streamlit & Plotly)                     │
│                                                                                        │
│   ┌───────────────────────────────┐          ┌──────────────────────────────────────┐  │
│   │   23-Artifact Registry        │          │   Cryptographic Integrity Engine     │  │
│   │   Expected SHA-256 Hashes     │◄─────────┤   Byte-level SHA-256 Verification    │  │
│   └──────────────┬────────────────┘          └──────────────────┬───────────────────┘  │
│                  │                                              │                      │
│                  ▼                                              ▼                      │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│   │               AST Import Guard (Enforces Read-Only Boundary)                    │  │
│   │     PROHIBITED: src/core, src/simulation, src/backtest, Database Writes         │  │
│   └─────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Cryptographic SHA-256 Verification:** Every research artifact loaded by the dashboard is verified against its registered digest in [`src/dashboard/artifacts/registry.py`](src/dashboard/artifacts/registry.py). Tampered or truncated files trigger an immediate `ArtifactIntegrityError`.
2. **Read-Only SQLite Database (`?mode=ro`):** The processed research database `data/processed/gmdb.db` is opened strictly read-only with SQLite `PRAGMA query_only = ON;`. Write queries (`INSERT`, `UPDATE`, `DELETE`, `CREATE`) raise operational errors.
3. **AST Architecture Guards:** Dedicated test suites inspect the Abstract Syntax Tree of the dashboard modules to ensure zero imports from calculation engines (`src/core`, `src/simulation`, `src/backtest`) or write layers.
4. **Data Classification Accounting:**
   - Total database observations: **8,908**
   - Genuine PIT records included: **8,900**
   - Retrospective series observations: **176** (annual World Bank CPI `FP.CPI.TOTL.ZG`)
   - Synthetic rows permanently excluded: **8**
   - Missing evidence count: **0**

---

## 7. Known Research Limitations

To maintain institutional integrity, the following limitations are explicitly documented:

1. **Covered Carry Trade is `UNEXECUTABLE`:** A truly risk-free covered interest parity arbitrage requires institutional forward exchange contracts ($F_{t_0, t_1}$). Because genuine forward quotes are unavailable in public historical feeds, the covered strategy is classified as `UNEXECUTABLE` (Config 6).
2. **2024 Portfolio Holdout is `UNAVAILABLE`:** The 2024 out-of-sample period has factor observations available, but out-of-sample portfolio execution is classified as **`UNAVAILABLE`** (`is_available: false`). No artificial equity curve has been simulated or backfilled.
3. **Discrete Execution Approximation:** Backtest results reflect discrete trade settlements over 30-day tenors. Continuous intermediate daily equity curves are deliberately not interpolated to prevent misleading volatility metrics.
4. **Simulations Are Not Realized Performance:** Monte Carlo trajectories represent stochastic forward model distributions calibrated to 2020–2023 empirical variance, not realized historical performance.
5. **No Guarantee of Profitability:** The historical strategy underperformed the risk-free EUR deposit benchmark (annualized alpha -92.9 bps, Sharpe -0.039) and incurred a max drawdown of -3.52%.

---

## 8. Technology Stack

- **Runtime & Language:** Python 3.11 and Python 3.12
- **Dashboard Framework:** Streamlit (>= 1.32.0)
- **Data Visualization:** Plotly (>= 5.20.0)
- **Numerical Computing:** NumPy (>= 1.26.0), SciPy (>= 1.11.0), Pandas (>= 2.1.0)
- **Data Contracts & Schemas:** Pydantic (>= 2.6.0)
- **Storage & Ingestion:** SQLite3, SQLAlchemy (>= 2.0.0), Alembic (>= 1.13.0), HTTPX (>= 0.27.0)
- **Quality Assurance & Testing:** Pytest (>= 8.0.0), Ruff (>= 0.8.0), Playwright
- **Package Management:** `uv` by Astral (recommended)

---

## 9. Repository Structure

```
The-Infinite-Money-Glitch-Detector/
├── src/
│   ├── core/                    # Mathematical foundations, FX quote logic, currency codes
│   ├── data/                    # Ingestion adapters, database models, Point-in-Time store
│   ├── backtesting/             # Cash flow accounting, settlement calendars, execution engines
│   ├── simulation/              # Monte Carlo models, GARCH calibrations, stress testing
│   ├── schemas/                 # Pydantic data contracts for artifacts and observations
│   └── dashboard/               # Streamlit research dashboard presentation layer
│       ├── app.py               # Main landing page & navigation
│       ├── artifacts/           # 23-artifact registry, SHA-256 verifier, typed loaders, DB helper
│       ├── components/          # Reusable UI cards, tables, filters, Plotly chart builders
│       └── pages/               # Six specialized research dashboard pages
├── data/
│   ├── processed/               # Authoritative SQLite database (gmdb.db)
│   └── results/                 # Authoritative research artifacts
│       ├── phase_3_2_2_3_3/     # 6 Backtest configuration artifacts
│       └── phase_4_1_2_2_3/     # 17 Monte Carlo, stress & holdout artifacts
├── tests/                       # 1,094 automated tests covering math, data, simulation, UI
├── docs/                        # Architecture specs, audit reports, deployment guide, screenshots
│   ├── PHASE_5_4_FINAL_AUDIT_REPORT.md   # Final 15-dimension independent audit report
│   ├── DEPLOYMENT_GUIDE.md               # Production operations and deployment manual
│   └── screenshots/                      # 14 verified browser QA screenshots and report
├── pyproject.toml               # Build configuration, dependencies, tool settings
└── uv.lock                      # Deterministic dependency lockfile
```

---

## 10. Installation & Setup

### Prerequisites
- Python 3.11 or 3.12
- Git
- `uv` (recommended) or `pip`

### Step 1: Clone Repository
```bash
git clone https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector.git
cd The-Infinite-Money-Glitch-Detector
```

### Step 2: Environment Setup & Dependencies

#### Using `uv` (Recommended)
```bash
uv venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate
uv sync
```

#### Using Standard `pip`
```bash
python -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

---

## 11. Running the Research Dashboard

### Local Development Execution
```bash
uv run streamlit run src/dashboard/app.py
```
Open your browser and navigate to:
```
http://localhost:8501
```

### Headless Production Service
To run as a system daemon or containerized service:
```bash
uv run streamlit run src/dashboard/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
```

### Healthcheck Endpoint
The service provides a built-in healthcheck:
```bash
curl -f http://localhost:8501/_stcore/health
```
Returns HTTP 200 `OK` when the Streamlit process is healthy and serving pages.

---

## 12. Testing and Quality Assurance

The repository maintains an extensive test suite with **1,094 passing tests** across 53 test modules:

```bash
# Run the complete test suite
uv run pytest -p no:cacheprovider

# Run dashboard-specific architectural and page tests
uv run pytest tests/test_dashboard*.py

# Run static analysis and linting
uv run ruff check .

# Check formatting across dashboard and tests
uv run ruff format --check src/dashboard tests/test_dashboard*.py
```

### Continuous Integration (CI) Matrix
Every push and pull request is validated on GitHub Actions across:
- **Ubuntu Latest / Python 3.11**
- **Ubuntu Latest / Python 3.12**
- Checks include dependency synchronization, Ruff linting, and full Pytest execution.

---

## 13. Production Deployment & Operations

For deployment checklists, system requirements, Nginx reverse-proxy configuration, systemd service units, and monitoring guidelines, consult the authoritative guide:

📖 **[Production Deployment & Operations Guide](docs/DEPLOYMENT_GUIDE.md)**

*Note: The platform is a research dashboard. Creating a release does not perform an automated public cloud deployment.*

---

## 14. Documentation and Audit History

- **Final Independent Audit Report:** [`docs/PHASE_5_4_FINAL_AUDIT_REPORT.md`](docs/PHASE_5_4_FINAL_AUDIT_REPORT.md)
- **Deployment & Operations Guide:** [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md)
- **Dashboard Architecture Specification:** [`docs/PHASE_5_DASHBOARD_ARCHITECTURE.md`](docs/PHASE_5_DASHBOARD_ARCHITECTURE.md)
- **Visual QA Report & Screenshots:** [`docs/screenshots/`](docs/screenshots/)
- **GitHub Actions Workflows:** [Actions Runs](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/actions)
- **Release v1.0.0:** [GitHub Release v1.0.0](https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector/releases/tag/v1.0.0)

---

## 15. Disclaimer

This software and its documentation are developed strictly for **academic research, educational analysis, and risk modeling purposes**.

Nothing contained in this repository, its models, its simulated paths, or its dashboard constitutes financial advice, investment advice, an endorsement of any trading strategy, or a solicitation to buy or sell securities, currencies, or derivatives. The authors and maintainers assume no liability for financial losses incurred from using these models or code.

---

## 16. License and Contributions

**Copyright © 2026 Aayush Sahu. All rights reserved.**

This codebase and associated research artifacts are proprietary research. No open-source license is granted at this time. Unauthorized copying, distribution, modification, or commercial exploitation is strictly prohibited without prior written permission.

Contributions are currently limited to internal project collaborators and invited research partners.
