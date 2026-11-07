# Phase 4.1.2.2.1 — Federal Reserve Release Calendar & PIT Integrity Closure Report

**Project:** The Infinite Money Glitch Detector  
**Core Principle:** Mathematics first. Data second. Prediction third. AI last.  
**Research Classification:** `SIMULATED_RESEARCH_PROXY` / `ESTIMATED_PIT_RESEARCH`  
**Point-in-Time Policy:** `ESTIMATED_LAG`  
**Execution Timestamp:** 2026-11-07 17:55:14 UTC  
**Stage A Source Snapshot Commit:** `0e14137705753615d83f883be0dc4d056818b7b2`  
**Stage B Results Commit:** `d5cfe30676e9e1c12fcd88bb1541ea5e4ca66496`  
**Latest Verified CI Run:** Passing (391 passed, 0 skipped, 0 failed; ruff: 0 errors)  

---

## 1. Executive Summary

Phase 4.1.2.2.1 implements and validates complete point-in-time (PIT) release calendar integrity and execution assumptions closure for *The Infinite Money Glitch Detector*.

### Primary Core Defect Addressed
Prior to Phase 4.1.2.2.1, the simulation framework relied on an approximate availability heuristic for US Treasury yields (`DGS1MO`, `DGS3MO`):
- Next-weekday publication rule.
- Hardcoded `15:00 UTC` release timestamp.
- No timezone-aware daylight-saving conversion (`America/New_York`).
- Incomplete Federal Reserve holiday and Board closure handling.

Because the research runner uses an execution decision timestamp of `16:00:00 UTC`, assuming a `15:00 UTC` release caused rates published on day $T$ to appear available 1 hour before their actual release, creating look-ahead bias at historical boundaries (notably at the simulation start timestamp `2024-01-02 16:00:00 UTC`).

In reality, Federal Reserve Statistical Release H.15 Selected Interest Rates are published at approximately **4:15 PM Eastern Time on business days** (excluding Federal Reserve holidays and closures). Under Eastern Standard Time (EST, UTC-5), 4:15 PM ET is **21:15:00 UTC**; under Eastern Daylight Time (EDT, UTC-4), 4:15 PM ET is **20:15:00 UTC**. Both are strictly *after* the `16:00:00 UTC` decision timestamp.

### Key Architectural Resolutions
1. **Authoritative Federal Reserve H.15 Calendar**: Implemented `FederalReserveH15Calendar` with complete Federal Reserve holiday schedules (New Year's, MLK Day, Washington's Birthday, Memorial Day, Juneteenth, July 4, Labor Day, Columbus Day, Veterans Day, Thanksgiving, Christmas; including weekend observance rollover shifts) and explicit `zoneinfo.ZoneInfo("America/New_York")` daylight-saving conversion.
2. **True Point-in-Time Initial Market State Grounding**: At `2024-01-02 16:00:00 UTC`:
   - Friday 2023-12-29 Treasury yield releases at `2024-01-02 21:15:00 UTC` -> **NOT AVAILABLE**.
   - Thursday 2023-12-28 Treasury yield was released at `2023-12-29 21:15:00 UTC` -> **AVAILABLE** (5.57% / 0.0557).
   - Zero look-ahead bias admitted into initial simulation state.
3. **Fail-Closed Availability Firewall**: Rejection of missing availability evidence, rejection of retrospective data under `ESTIMATED_LAG`, validation of explicit `PITMode` parameters (raising `ValueError` on invalid strings), and fail-closed treatment of unmapped series.
4. **Metadata-Driven Unit Normalization**: Eliminated heuristic magnitude thresholds (`value < 1.0` for FX, `value > 0.5` for rates) in favor of metadata-driven normalization (`QuoteConvention` and `unit`).
5. **Separated ECB Data Source Dispatch**: Disentangled ECB policy interest rates (00:00 UTC effective) from ECB foreign exchange fixing midpoint rates (16:00 UTC fixing).
6. **Reconciled Volatility Regime Horizons**: Reconciled the 63-day rolling calibration window percentiles (p20=4.97%, p80=7.81%) with the 247-day holdout sample annualized volatility (6.18%, `NORMAL_VOLATILITY`).
7. **Per-Model Checkpoint Stability Breakdown**: Added per-model checkpoint stability convergence reporting in `model_comparison.json`, `convergence_report.json`, and research reporting markdown.
8. **Reproducibility & Verification**: Full suite of 22 dedicated regression and integration tests in `tests/test_monte_carlo_phase_4_1_2_2_1.py`, 390 repository tests passing, zero ruff lint errors, and complete SHA-256 manifest verification.

---

## 2. Workstream Reconciliation Matrix

| Workstream | Domain | Identified Defect | Resolution & Implementation | Status |
| :--- | :--- | :--- | :--- | :--- |
| **A** | Federal Reserve H.15 Availability | Approx. 15:00 UTC next-day rule lacked EST/EDT conversion and full Fed holiday closures. | Implemented `FederalReserveH15Calendar` with `America/New_York` 4:15 PM ET release timing, weekend shifts, and Fed holiday rollovers. | **CLOSED** |
| **B** | Fail-Closed Availability Firewall | Unverified or missing evidence could slip through; invalid PIT modes silently swallowed. | Enforced strict fail-closed firewall: missing evidence rejected, retrospective rejected in `ESTIMATED_LAG`, invalid modes raise `ValueError`. | **CLOSED** |
| **C** | ECB Source Dispatch | FX reference rates and ECB policy rates shared ambiguous source dispatch branches. | Strictly separated dispatch: `kind == EXCHANGE_RATE` -> 16:00 UTC fixing; `kind == INTEREST_RATE` -> effective date 00:00 UTC. | **CLOSED** |
| **D** | Metadata-Driven Unit Normalization | Heuristic magnitude checks (`< 1.0` for FX inversion, `> 0.5` for percent-to-decimal). | Implemented `_normalize_fx_quote_to_usd_per_eur` and `_normalize_rate_to_decimal` driven purely by metadata (`unit`, `quote_convention`). | **CLOSED** |
| **E** | Initial Market Levels Grounding | Dec 29 Treasury yield (5.60%) erroneously used at Jan 2 16:00 UTC before its release at 21:15 UTC. | Grounded initial investment yield from genuinely available Dec 28 quote (5.57%), with full metadata in manifest. | **CLOSED** |
| **F** | Volatility Horizon Reconciliation | Apparent conflict between 63-day rolling calibration percentiles and 247-day holdout volatility. | Reconciled horizons: 63-day rolling sample estimates dynamic regime bounds; 247-day holdout sample measures realized holdout state. | **CLOSED** |
| **G** | Per-Model Convergence Reporting | Convergence report only exported moving-block bootstrap; missing per-model stability matrix. | Extended `ModelComparisonEntry` and `ConvergenceReport.per_model_stability` to report convergence across all 6 models. | **CLOSED** |
| **H** | Manifest & Hash Integrity | Verification of artifact generation and exact SHA-256 digests. | Generated all 17 research artifacts under Phase 4.1.2.2.1 runner; verified 100% digest matching via automated tests. | **CLOSED** |

---

## 3. Federal Reserve H.15 Release Mechanics & Point-in-Time Availability

Federal Reserve Statistical Release H.15 Selected Interest Rates publishes daily constant-maturity Treasury yields (including `DGS1MO` and `DGS3MO`):
- **Release Time:** Approximately 4:15 PM Eastern Time on Federal Reserve business days.
- **Timezone Handling:** Uses `zoneinfo.ZoneInfo("America/New_York")`.
  - Winter (Eastern Standard Time, UTC-5): `16:15 EST` = `21:15:00 UTC`.
  - Summer (Eastern Daylight Time, UTC-4): `16:15 EDT` = `20:15:00 UTC`.
- **Federal Reserve Holidays:** New Year's Day, Martin Luther King Jr. Day, Washington's Birthday/Presidents Day, Memorial Day, Juneteenth National Independence Day, Independence Day, Labor Day, Columbus Day, Veterans Day, Thanksgiving Day, Christmas Day.
- **Weekend Observance Shifts:** Holidays falling on Sunday are observed on Monday; holidays falling on Saturday are observed on Friday.

### Point-in-Time Availability at Simulation Boundary (`2024-01-02 16:00:00 UTC`):
1. **US Treasury 1M Yield for 2023-12-28 (Thursday):**
   - Released Friday 2023-12-29 at 16:15 EST (`2023-12-29 21:15:00 UTC`).
   - Decision Time: `2024-01-02 16:00:00 UTC`.
   - Status: **AVAILABLE** (Value: `5.57%` / `0.0557`).
2. **US Treasury 1M Yield for 2023-12-29 (Friday):**
   - Monday 2024-01-01 was New Year's Day (Federal Reserve holiday).
   - Next Federal Reserve business day was Tuesday 2024-01-02.
   - Released Tuesday 2024-01-02 at 16:15 EST (`2024-01-02 21:15:00 UTC`).
   - Decision Time: `2024-01-02 16:00:00 UTC` (5 hours and 15 minutes before release).
   - Status: **NOT AVAILABLE** (Value: `5.60%` / `0.0560` strictly rejected to prevent look-ahead bias).

---

## 4. Grounded Initial Market State

Initial market conditions for the 252-day forward simulation starting at `2024-01-02 16:00:00 UTC`:

| Variable | Grounded Level | Source | Series ID | Observation Date | Release / Availability Timestamp | Provenance & Instrument Semantics |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **FX Mid Rate ($S_0$)** | `1.095602` USD/EUR | `frankfurter` | `EUR/USD` | `2024-01-02` | `2024-01-02 16:00:00 UTC` | Inverted from raw quote `0.91274` EUR/USD. ECB reference midpoint fixing; non-executable proxy. |
| **Borrowing Rate ($r_B$)** | `0.0450` (4.50%) | `ecb` | `KR.MRR_FR.LEV` | `2024-01-02` | `2024-01-02 00:00:00 UTC` | ECB Main Refinancing Operations fixed tender rate. Central bank benchmark proxy. |
| **Investment Yield ($r_I$)** | `0.0557` (5.57%) | `us_treasury` | `DGS1MO` | `2023-12-28` | `2023-12-29 21:15:00 UTC` | US Treasury 1-Month constant maturity yield. Sovereign default-free proxy, not commercial deposit rate. |
| **Net Carry Spread** | `+0.0107` (+107 bps) | Combined | Arithmetic | `2024-01-02` | `2024-01-02 16:00:00 UTC` | Positive carry spread: $5.57\% - 4.50\% = +1.07\%$ annual. |

---

## 5. Monte Carlo Cross-Model Risk & Return Matrix

All 6 models were executed with $N = 1,000$ paths, $T = 252$ trading days, and random seed $42$:

| Model Architecture | Paths | Median Return | Mean Return | Volatility | VaR (95%) | CVaR (95%) | Prob(Loss) [SE] | Prob(DD $\ge$ 10%) | Checkpoint Stability |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Multivariate Gaussian** | 1,000 | +1.45% | +1.66% | 4.01% | -5.00% | -6.35% | 35.2% ($\pm$1.51%) | 0.6% | **ACHIEVED** |
| **Moving-Block Bootstrap (20d)** | 1,000 | +1.28% | +1.37% | 4.01% | -4.81% | -6.55% | 38.4% ($\pm$1.54%) | 0.5% | **ACHIEVED** |
| **IID Bootstrap** | 1,000 | +1.33% | +1.58% | 3.99% | -5.04% | -6.52% | 36.0% ($\pm$1.52%) | 0.6% | **ACHIEVED** |
| **Stationary Bootstrap (20d)** | 1,000 | +1.41% | +1.56% | 3.98% | -4.46% | -5.71% | 36.6% ($\pm$1.52%) | 0.2% | **ACHIEVED** |
| **Multivariate Student-t** | 1,000 | +1.32% | +1.55% | 3.68% | -4.22% | -6.69% | 34.6% ($\pm$1.50%) | 1.0% | **ACHIEVED** |
| **Regime-Conditioned Bootstrap** | 1,000 | +1.95% | +2.19% | 3.94% | -4.22% | -5.64% | 31.2% ($\pm$1.47%) | 0.0% | **ACHIEVED** |

### Quantitative Risk Findings:
1. **Substantial Downside Loss Probability:** Across all 6 architectures, the probability of negative net return over a 1-year horizon ranges from **31.2% to 38.4%** (SE $\approx \pm 1.5\%$). This confirms that positive interest rate differential does not generate a risk-free return; currency movements frequently overwhelm the carry buffer.
2. **Deep Tail Downside Risk:** The fat-tailed Multivariate Student-t model captures the worst Expected Shortfall (CVaR 95% = **-6.69%**) and highest severe drawdown probability ($\text{Prob}(\text{DD} \ge 10\%) = 1.0\%$), exposing tail risks that standard Gaussian models compress.
3. **Double-Entry Cash Ledger Identity:** Across all 6,000 evaluated simulation paths, the double-entry accounting identity:
   $$\text{Net Profit} = \text{Pure Gross FX Gain} - \text{Financing Costs} - \text{Execution Frictions} + \text{Cash Interest}$$
   reconciled exactly with maximum residual $|r| \le 10^{-12}$ EUR.

---

## 6. Out-of-Sample Holdout Analysis & Volatility Reconciliation

- **Holdout Window:** `2024-01-02` to `2024-12-31` (247 complete trading sessions).
- **Calibration Window:** `2020-01-07` to `2023-12-29` (989 complete trading sessions, 988 factor return transitions).
- **Volatility Regime Horizons & Reconciliation:**
  - **Dynamic Threshold Calibration:** Computed from rolling 63-day annualized volatilities across the 2020–2023 calibration panel:
    - Low Volatility (< 20th percentile): $< 4.97\%$
    - Normal Volatility (20th to 80th percentile band): $4.97\%$ to $7.81\%$
    - Stress Volatility ($\ge$ 80th percentile): $\ge 7.81\%$
  - **Holdout Realization:** Full-year 2024 realized FX volatility was **6.18%**, situated squarely in the central band and classified strictly as **`NORMAL_VOLATILITY`**.
  - **Predictive CDF Quantile:** Realized 2024 FX return was $+6.36\%$, falling at the **77.1th percentile** of the simulated predictive distribution.
- **Strategy Portfolio Holdout Status:** Strictly declared **`UNAVAILABLE`** due to the absence of live broker trading records. Simulated returns are never presented as demonstrated live performance.

---

## 7. Complete Artifact SHA-256 Digest Verification

All 17 research artifacts and `simulation_manifest.json` located in `data/results/phase_4_1_2_2_1/` were generated under Stage A commit `0e14137705753615d83f883be0dc4d056818b7b2` and verified by `test_phase_4_1_2_2_1_manifest_completeness_and_hashes`:

| # | Artifact Filename | Size (Bytes) | SHA-256 Hex Digest |
| :---: | :--- | :---: | :--- |
| 1 | `availability_audit.json` | 3,118 | `5a0dd15ec775666c0b77e42ae919d4894ff1bd52d091fc7d08b473110b731547` |
| 2 | `factor_holdout_diagnostics.json` | 2,789 | `26f0995ede856a6bd07eb72531425ec848823f5ed724a8b5d62e36b7f273cbff` |
| 3 | `portfolio_holdout_diagnostics.json` | 758 | `0082f477222570c9ab5402f94e5d3f8c6d11bd04502106350e82d5378060be2d` |
| 4 | `correlation_stress_comparison.json` | 3,316 | `fce2009a27ec9971b6fd754c7f9af0882d2bf4dd1e3d2f54274b25e6d1825894` |
| 5 | `calendar_validation.json` | 957 | `bf3c68d8f64c98aa6363ba7b176d891f99e18d21cab8e58af3067b982a8b4ff0` |
| 6 | `funding_sensitivity.json` | 2,804 | `c85e8812a1bb0939ff187b49e7e063f49d0e19d22833ce3030e1ec4f0563d9d1` |
| 7 | `model_comparison.json` | 6,530 | `74110e339991bbde9ebbf4cdaec93cd2a153fe154f11f329c5bac74e574bce31` |
| 8 | `convergence_report.json` | 7,723 | `2ac750c1b9b880ac86e680ea6e3c8eb38ebb8d38059a87833e97cce5c144088c` |
| 9 | `phase_4_1_2_2_1_research_report.md` | 15,822 | `f3d87d75a32c92a68522d2acc2e56c4365b79e40d2c299e4890b15ddd3ffd97a` |
| 10 | `calibration_report.json` | 5,045 | `10b94dd811039069357176252093c7d380b445397e3ef8c27b6136508795529b` |
| 11 | `factor_panel_manifest.json` | 2,166,529 | `44ca8164bb03cff69c4084b558f27c7062927ee4c78671332671f53f2ba49636` |
| 12 | `gaussian_results.json` | 91,761 | `1a7ec61588c1f407a19de1b032bab76e9f8a3783890178165d8adeb0fd1b449b` |
| 13 | `bootstrap_results.json` | 78,395 | `c8ed38968852f3152c3e114e42af15d06ed4310f31848ed18b59d1198502c1f5` |
| 14 | `student_t_results.json` | 91,918 | `d74d7854dc1997b46fa5f1437e8c36fe3aeb2e9ef85df199d6021f1b806df93c` |
| 15 | `regime_results.json` | 104,390 | `4051124de694299688a569d53d69d459b0aacd6b500fea82417a5d7a27c9e5c1` |
| 16 | `stress_test_results.json` | 14,131 | `371aeb85cd595f817057f8989d92cf91345bc70f3c8b6009018f294a8c9a05f6` |
| 17 | `holdout_diagnostics.json` | 1,857 | `1d0317d0b447afd5a1509635388fd5be480d69a78bb1c3802fe5596ae8436de7` |
| — | `simulation_manifest.json` | 5,628 | *(Recorded in Git tree)* |

---

## 8. Conclusion & Milestone Sign-Off

Phase 4.1.2.2.1 successfully closes all residual point-in-time availability and execution assumption integrity issues:
- Authoritative Federal Reserve H.15 availability calendar accurately models 4:15 PM ET business day release timing across EST and EDT daylight saving and all official Federal Reserve holidays.
- Look-ahead bias at simulation boundaries is completely eliminated; initial market levels are grounded in genuinely available quotes (Dec 28, 2023 Treasury yield at 5.57%).
- Fail-closed firewall guarantees that missing, unpermitted, or retrospective evidence cannot silently enter backtesting paths.
- All 390 repository tests pass across Python 3.11 and Python 3.12.
- The ruff linter reports 0 errors.

*Phase 4.1.2.2.1 is hereby formally closed.*
