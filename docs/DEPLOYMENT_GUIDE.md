# Production Deployment & Operations Guide — Research Dashboard
## The Infinite Money Glitch Detector

**Project:** The Infinite Money Glitch Detector  
**System:** Interactive Quantitative Research Dashboard (Streamlit & Plotly)  
**Milestone:** Phase 5.4 Production Readiness  
**Core Principle:** Mathematics first. Data second. Prediction third. AI last.

---

## 1. Overview & System Purpose

The dashboard is an institutional, strictly read-only analytical presentation layer designed to explore, visualize, and inspect precomputed, cryptographically verified research outputs from Phase 3 (Carry Trade Backtesting) and Phase 4 (Multi-factor Monte Carlo Simulations & Stress Testing).

It does **not** execute live trading, place broker orders, run real-time Monte Carlo simulations, or mutate the underlying economic databases.

---

## 2. Supported Platforms & Environments

- **Operating Systems**: Linux (Ubuntu 22.04 LTS / 24.04 LTS recommended), macOS (13+), Windows (10/11 / Server 2022).
- **Python Versions**: Python 3.11 and Python 3.12 (explicitly validated on CI across both versions).
- **Package Manager**: `uv` (recommended) or standard `pip` (>= 23.0).

---

## 3. Installation & Dependency Setup

### Option A: Using `uv` (Recommended)
```bash
# Clone repository
git clone https://github.com/Aayushashsahu/The-Infinite-Money-Glitch-Detector.git
cd The-Infinite-Money-Glitch-Detector

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
uv sync
```

### Option B: Using Standard `pip`
```bash
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -e .
```

---

## 4. Required Files & Storage Hierarchy

Before starting the dashboard service, verify that all authoritative research artifacts and the local SQLite database exist in the working directory:

```
data/
├── processed/
│   └── gmdb.db                         # Authoritative processed SQLite database (SHA-256: 7913ae5c...)
└── results/
    ├── phase_3_2_2_3_3/                # 6 Historical Backtest Configuration Artifacts
    │   ├── config_1_strict_pit.json
    │   ├── config_2_estimated_schedule.json
    │   ├── config_3_strict_quotes.json
    │   ├── config_4_matched_benchmark.json
    │   ├── config_5_mismatched_benchmark.json
    │   └── config_6_covered_rejection.json
    └── phase_4_1_2_2_3/                # 17 Monte Carlo, Stress & Holdout Artifacts
        ├── calibration_report.json
        ├── factor_panel_manifest.json
        ├── model_comparison.json
        ├── gaussian_results.json
        ├── bootstrap_results.json
        ├── student_t_results.json
        ├── regime_results.json
        ├── convergence_report.json
        ├── stress_test_results.json
        ├── correlation_stress_comparison.json
        ├── funding_sensitivity.json
        ├── holdout_diagnostics.json
        ├── factor_holdout_diagnostics.json
        ├── portfolio_holdout_diagnostics.json
        ├── availability_audit.json
        ├── calendar_validation.json
        └── simulation_manifest.json
```

---

## 5. Starting the Dashboard Application

### Standard Local Execution
```bash
uv run streamlit run src/dashboard/app.py
```

### Production Headless Service
To run as a system service (e.g. via `systemd` or supervisor) on a dedicated port:
```bash
uv run streamlit run src/dashboard/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
```

### Healthcheck Endpoint
The service provides a built-in healthcheck endpoint at:
```http
GET http://localhost:8501/_stcore/health
```
Returns HTTP 200 `OK` when the Streamlit process is healthy and serving pages.

---

## 6. Architectural Guarantees & Security Model

1. **Strictly Read-Only SQLite Access**:
   - The database connection string is permanently set to `file:data/processed/gmdb.db?mode=ro`.
   - Every SQLite connection immediately executes `PRAGMA query_only = ON;`.
   - Any SQL statement attempting `INSERT`, `UPDATE`, `DELETE`, `DROP`, or `CREATE` is rejected by the SQLite engine with an operational error.
2. **Cryptographic SHA-256 Artifact Verification**:
   - All 23 JSON artifacts are registered with fixed SHA-256 digests in `src/dashboard/artifacts/registry.py`.
   - If an artifact file is modified, corrupted, or replaced, `verify_registered_artifact()` raises `ArtifactIntegrityError` and aborts page rendering.
3. **Zero Engine Imports (AST Invariant)**:
   - Dashboard presentation modules strictly import from `dashboard.artifacts` and `dashboard.components`.
   - Prohibited packages: `src/core`, `src/analytics`, `src/backtest`, `src/simulation`, and repository write layers.
4. **No Secrets or Credentials**:
   - The dashboard requires zero API keys, cloud tokens, database passwords, or secret environment variables.
   - Never commit `.env` files with private secrets to the repository.

---

## 7. Known Operational & Research Limitations

1. **Historical Backtest Terminal Nature**:
   - The historical backtest (Config 2) is a discrete trade-by-trade terminal execution over 1,236 daily transitions.
   - Intermediate daily equity curves are explicitly marked as not modeled to prevent interpolation bias.
2. **2024 Portfolio Holdout State**:
   - Out-of-sample portfolio holdout is strictly classified as **`UNAVAILABLE`** (`is_available: false`).
   - In accordance with the foundational research principle, no portfolio equity curve is fabricated or imputed.
3. **Static Research Artifacts**:
   - Modifying research models or running new Monte Carlo scenarios requires re-executing the Phase 4 simulation pipelines outside the dashboard.

---

## 8. Deployment Verification Checklist

- [ ] Python 3.11 or 3.12 active in virtual environment (`python --version`).
- [ ] Dependencies installed cleanly without warnings (`uv sync` or `pip install -e .`).
- [ ] All 23 research artifacts exist in `data/results/`.
- [ ] SQLite database `data/processed/gmdb.db` exists (SHA-256: `7913ae5c...`).
- [ ] All 74 dashboard tests pass locally (`uv run pytest tests/test_dashboard*.py`).
- [ ] Service starts cleanly in headless mode on designated port.
- [ ] Healthcheck responds HTTP 200 (`curl -f http://localhost:8501/_stcore/health`).
- [ ] Visual inspection confirms all six pages render with zero exceptions.
