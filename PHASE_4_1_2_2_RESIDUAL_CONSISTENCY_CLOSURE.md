# Phase 4.1.2.2 — Residual Consistency & Execution Assumptions Closure

**Project:** The Infinite Money Glitch Detector  
**Core Principle:** Mathematics first. Data second. Prediction third. AI last.  
**Research Classification:** `SIMULATED_RESEARCH_PROXY` / `ESTIMATED_PIT_RESEARCH`  
**Point-in-Time Policy:** `ESTIMATED_LAG`  
**Execution Timestamp:** 2026-11-07 15:39:12 UTC  
**Stage A Source Snapshot Commit:** `839e535a724decdc9f6b50061aeef010945ae7fe`  
**Stage B Results Commit:** `afe9c99fd50011d4ac14393c40539ae70204d66a`  

---

## 1. Executive Summary

Phase 4.1.2.2 achieves complete research-integrity, execution assumptions, and provenance closure following the independent review of Phase 4.1.2.1. In accordance with the guiding mandate, no new strategy features were added, no return optimization was performed, and Phase 5 was not initiated.

The primary objective was resolving the residual inconsistencies across:
1. **Revision-aware point-in-time observation selection**: Eliminating up-front reduction; selecting the latest valid revision as of each session's decision timestamp (`16:00:00 UTC`).
2. **Standardized volatility taxonomy**: Eliminating conflicting naming across the codebase in favor of a three-state taxonomy (`LOW_VOLATILITY`, `NORMAL_VOLATILITY`, `STRESS_VOLATILITY`) calibrated dynamically from the calibration panel.
3. **Reconciled calibration sample sizes**: Reconciling the 990-trading-day calibration window ($T = 991$ observation days vs. $T - 1 = 990$ factor return transitions) and dynamically deriving all counts, worst CVaR figures, and holdout days across all reporting and tests.
4. **Strict strategy calendar enforcement**: Enforcing `strict_calendar=True` by default in `CarryTradeScenarioStrategy`, validating every path against the `JointTarget2FedCalendar`, and rejecting weekends, holidays, length mismatches, and out-of-order dates.
5. **Grounded initial market levels**: Dynamically grounding initial FX rate (1.095602 USD/EUR), borrowing rate (4.50%), and investment yield (5.60%) from the latest available historical observations strictly as of the simulation start timestamp (`2024-01-02 16:00:00 UTC`), recording full provenance in the manifest.
6. **Convergence and checkpoint stability nomenclature**: Replacing claims of asymptotic mathematical convergence with finite sample `CHECKPOINT_STABILITY`, and disclosing the 50-tail-observation sample limitation for CVaR at 1,000 paths ($\alpha = 0.05$).
7. **Economic instrument and data-source semantics**: Explicitly disclosing proxy definitions (ECB reference rate as non-executable proxy, Treasury yields as non-deposit proxies, policy rate as non-commercial borrowing rate).
8. **Reproducibility and manifest integrity**: Adopting a strict two-stage snapshot workflow, recording exact commit SHA, database hash (`7913ae5c...`), random seed (`42`), and exact SHA-256 digests for all 17 research artifacts.
9. **Testing, linting, and CI hygiene**: Configuring `ruff` in `pyproject.toml` and `.github/workflows/ci.yml` across Python 3.11 and 3.12, eliminating all 744 lint errors to 0, and adding 15 dedicated regression tests in `test_monte_carlo_phase_4_1_2_2.py`.

---

## 2. Workstream Reconciliation Matrix

| Workstream | Domain | Identified Issue | Resolution & Implementation | Status |
| :--- | :--- | :--- | :--- | :--- |
| **A** | Point-in-Time Revision Awareness | Up-front deduplication discarded older revisions valid at earlier decision times. | Replaced up-front reduction with candidate pools; `resolve_observation_as_of` selects latest revision available strictly as of `as_of_dt`. | **CLOSED** |
| **B** | Volatility Regime Taxonomy | Fragmented naming (`LOW`, `HIGH`, `STRESS`, `MEDIUM`). | Standardized on `LOW_VOLATILITY` (< p20), `NORMAL_VOLATILITY` (p20–p80), and `STRESS_VOLATILITY` ($\ge$ p80) with dynamic thresholds. | **CLOSED** |
| **C** | Sample Size Reconciliation | Discrepancy between 991 observation days and 990 return transitions; hardcoded -6.20% CVaR. | Dynamically derived all sample counts, transitions, worst CVaR (-6.69%), and holdout days across all reporting templates. | **CLOSED** |
| **D** | Strategy Calendar Enforcement | Strategy allowed dateless paths and unvalidated weekends by default. | Set `strict_calendar=True` by default; implemented `validate_calendar_dates` checking `JointTarget2FedCalendar`. | **CLOSED** |
| **E** | Initial Market State Grounding | Hardcoded initial levels (1.10 FX, 4.0% borrow, 5.3% invest) detached from simulation start. | Implemented `resolve_initial_market_levels()`, resolving 1.095602 FX, 4.50% borrow, 5.60% invest as of 2024-01-02 16:00 UTC. | **CLOSED** |
| **F** | Convergence & Checkpoint Stability | Claimed asymptotic convergence with only 50 tail observations for CVaR. | Renamed to `CHECKPOINT_STABILITY`; added explicit disclosures on 50-tail-observation sample limitations. | **CLOSED** |
| **G** | Economic Instrument Semantics | Lack of explicit disclosure on rate executability vs proxy status. | Integrated explicit proxy declarations into Section 4 of research report and manifest metadata. | **CLOSED** |
| **H** | Manifest & Hash Integrity | Pre-closure commits, dirty working trees, and byte mismatches in CI. | Enforced two-stage workflow; verified exact SHA-256 digests for all 17 artifacts with 100% test coverage. | **CLOSED** |
| **I** | Testing, Linting & CI | 744 ruff lint errors; CI lack of ruff gate. | Configured ruff in `pyproject.toml` and `.github/workflows/ci.yml`; fixed 744 lint errors to 0; 368 tests passing. | **CLOSED** |

---

## 3. Dynamic Initial Market State Grounding

The simulation begins at `2024-01-02 16:00:00 UTC`. Initial market conditions were dynamically resolved from historical observations available under `ESTIMATED_LAG` policy:

| Variable | Grounded Value | Source ID | Series / Indicator ID | Raw Obs Date | Effective Availability | Provenance & Instrument Semantics |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **FX Rate ($S_0$)** | `1.095602` USD/EUR | `frankfurter` | `EUR/USD` (ECB Ref) | 2024-01-02 | 2024-01-02 16:00 UTC | Inverted from raw quote `0.91274` EUR/USD. Non-executable ECB reference midpoint proxy. |
| **Borrowing Rate ($r_B$)** | `0.0450` (4.50%) | `ecb` | `KR.MRR_FR.LEV` | 2024-01-02 | 2024-01-02 16:00 UTC | ECB Main Refinancing Operations fixed tender rate. Policy benchmark proxy, not commercial interbank borrowing rate. |
| **Investment Yield ($r_I$)** | `0.0560` (5.60%) | `us_treasury` | `DGS1MO` | 2023-12-29 | 2024-01-01 15:00 UTC | US Treasury 1-Month constant maturity yield. Sovereign yield proxy, not commercial bank deposit rate. |
| **Net Carry Spread** | `+0.0110` (+110 bps) | Combined | Arithmetic Difference | 2024-01-02 | 2024-01-02 16:00 UTC | Initial positive carry spread of $5.60\% - 4.50\% = +1.10\%$ annual. |

*Note on US Treasury 1M Observation Date:* The latest Treasury quote genuinely available at `2024-01-02 16:00:00 UTC` is dated `2023-12-29`, because the `2024-01-02` quote is not published until `2024-01-03 15:00:00 UTC`. Point-in-time integrity strictly prevented look-ahead leakage.

---

## 4. Monte Carlo Cross-Model Risk & Return Matrix

All 6 models were executed with $N = 1,000$ paths, $T = 252$ trading days, and random seed $42$ on the clean Stage A snapshot:

| Model Architecture | Paths | Median Ret | Mean Ret | Volatility | VaR (95%) | CVaR (95%) | Prob(Loss) | Prob(DD $\ge$ 10%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Multivariate Gaussian** | 1,000 | +1.59% | +1.74% | 4.01% | -4.93% | -6.15% | 35.4% ($\pm$1.51%) | 0.3% |
| **Moving-Block Bootstrap (20d)** | 1,000 | +1.20% | +1.35% | 4.01% | -4.68% | -6.55% | 36.6% ($\pm$1.52%) | 0.3% |
| **IID Bootstrap** | 1,000 | +1.25% | +1.50% | 4.00% | -4.80% | -6.50% | 36.9% ($\pm$1.53%) | 0.3% |
| **Stationary Bootstrap (20d)** | 1,000 | +1.25% | +1.59% | 3.98% | -4.36% | -5.70% | 36.1% ($\pm$1.52%) | 0.2% |
| **Multivariate Student-t** | 1,000 | +1.36% | +1.59% | 3.68% | -4.13% | -6.69% | 33.1% ($\pm$1.49%) | 1.0% |
| **Regime-Conditioned Bootstrap** | 1,000 | +1.92% | +2.08% | 3.95% | -4.12% | -5.83% | 31.9% ($\pm$1.47%) | 0.3% |

### Key Quantitative Findings:
- **Worst-Case Tail Risk:** The Multivariate Student-t model produced the most conservative tail risk estimate, with 95% CVaR of **-6.69%** and the highest probability of catastrophic drawdown ($\ge 10\%$) at **1.0%**.
- **Probability of Loss:** Across all 6 architectures, the probability of negative net return over a 1-year horizon ranges from **31.9% to 36.9%** (SE $\approx \pm 1.5\%$). This quantitatively demonstrates that cross-currency carry trade strategies carry substantial downside risk and do not represent riskless arbitrage ("infinite money glitches").
- **Double-Entry Accounting Ledger Guarantee:** In all 6,000 evaluated paths, cash ledger balance identity $|A_t + S_t \cdot B_t - W_t| \le 10^{-9}$ was maintained at every discrete step.

---

## 5. Checkpoint Stability & Sample Limitations Disclosure

- **Stability Status:** `CHECKPOINT_STABILITY_ACHIEVED` across sequential checkpoints $N \in \{25, 50, 100, 250, 500, 1000\}$.
- **Standard Error of Loss Probability:** Diminished from $\pm 8.94\%$ at $N=25$ to $\pm 1.51\%$ at $N=1000$.
- **Tail Sample Size Limitation Disclosure:** At $N=1,000$ paths and $\alpha = 0.05$, the left-tail sample contains exactly **50 observations**. While sufficient for descriptive checkpoint stability, 50 tail observations provide limited statistical precision for Expected Shortfall (CVaR).
- **Asymptotic Convergence Distinction:** Finite sample stability across discrete checkpoints does not establish asymptotic mathematical convergence. Tail risk estimates remain subject to finite sample variation.

---

## 6. Out-of-Sample Holdout Analysis & Regime Coverage

- **Holdout Period:** 2024-01-02 to 2024-12-31 (247 complete-case trading days).
- **Calibration Period:** 2020-01-06 to 2023-12-29 (990 factor return transitions, 991 observation days).
- **Dynamically Calibrated Volatility Thresholds:**
  - Lower Threshold (20th percentile): **4.97%**
  - Upper Threshold (80th percentile): **7.81%**
- **2024 Realized FX Volatility:** **6.18%**, situated between the 20th and 80th percentiles, classifying 2024 strictly as **`NORMAL_VOLATILITY`**.
- **Realized 2024 FX Return:** EUR appreciated $+6.36\%$ against USD, landing at the **76.2th percentile** of the predictive distribution.
- **Portfolio Holdout Status:** Strictly declared **`UNAVAILABLE`** due to the absence of executable live execution records. Simulated returns are never presented as validated live market returns.

---

## 7. Point-in-Time Availability Audit Reconciliation

- **Total Genuine Observations Evaluated:** 8,900
- **Exact Timestamp Verified Observations:** 0
- **Estimated Release Schedules:** 8,724 (Frankfurter FX, US Treasury constant maturity yields)
- **Retrospective Benchmark Observations:** 176 (ECB policy rate historical series)
- **Unreconciled Observations:** 0
- **Reconciliation Audit Status:** **`PASSED (100% Accounted)`**
- **Policy Enforcement:** Under `ESTIMATED_LAG`, all 8,724 estimated observations are used with documented release lags; retrospective observations are excluded from point-in-time decision gates.

---

## 8. Complete Artifact SHA-256 Digest Verification

All 17 research artifacts and `simulation_manifest.json` located in `data/results/phase_4_1_2_2/` were verified by `test_phase_4_1_2_2_manifest_completeness_and_hashes`:

| # | Artifact Filename | Size (Bytes) | SHA-256 Hex Digest |
| :---: | :--- | :---: | :--- |
| 1 | `availability_audit.json` | 2,897 | `70e413518e76798ae06b279868e3c6b36eafc34081850b0c536f56b50a15de61` |
| 2 | `factor_holdout_diagnostics.json` | 2,788 | `a708a91081af5e347fd9bb13a115ce88c38a6633d22fdf37c955ce86b7427b77` |
| 3 | `portfolio_holdout_diagnostics.json` | 758 | `0082f477222570c9ab5402f94e5d3f8c6d11bd04502106350e82d5378060be2d` |
| 4 | `correlation_stress_comparison.json` | 3,327 | `64361a42e406aac4329a96f834e3e34b9768d87f7c4e39d689f2c84599c7af42` |
| 5 | `calendar_validation.json` | 957 | `bf3c68d8f64c98aa6363ba7b176d891f99e18d21cab8e58af3067b982a8b4ff0` |
| 6 | `funding_sensitivity.json` | 2,804 | `c85e8812a1bb0939ff187b49e7e063f49d0e19d22833ce3030e1ec4f0563d9d1` |
| 7 | `model_comparison.json` | 3,353 | `0ab52d2a2ff58cbe2e24a7d2c0aa551fd7e7ff340668719721430582d659aad9` |
| 8 | `convergence_report.json` | 4,112 | `3bcbaf41cb5bf5a1808ba77710d1916eaf45bd9004c2707d1ab929c462c4f6f2` |
| 9 | `phase_4_1_2_2_research_report.md` | 14,389 | `789cbe36d4c13ca3c524d8a4c92d6eb06a223137b4d18b7eaaa6c48b05229845` |
| 10 | `calibration_report.json` | 5,028 | `e989ca5ce4a4a0086e7d621ea686e0e1eedc9399a6206efb1297e780c544a51c` |
| 11 | `factor_panel_manifest.json` | 2,168,477 | `a32c818a56c00e13ba81ce2d66098026f981137ae6ac7b04b9b7bd06916b3685` |
| 12 | `gaussian_results.json` | 91,924 | `ba2036d5d4e2d8c99116af00701853c7afb8d8fb719fdbd38ce61724ebe9bf21` |
| 13 | `bootstrap_results.json` | 78,036 | `a84d69cca28da194da982353f2be3bae2db2e132b00fd3317cbe7d6b0229d68f` |
| 14 | `student_t_results.json` | 91,971 | `90e8376417af0a53f60c3cbb4aa3998c69b1e6f4835c7b1d8d497e918e64c530` |
| 15 | `regime_results.json` | 103,632 | `8339f95fbcf7640d2800f1c1dfb2b7b212da5fd16c653a3ce30b0021ac966fd2` |
| 16 | `stress_test_results.json` | 14,128 | `e55a28aaec82086afd78b961e245a960f5140ef52d8cf723094d4b7c154f3572` |
| 17 | `holdout_diagnostics.json` | 1,856 | `4dc296adf90e3f394076612befe1c8f08806daeaa567d7159bb844c60bd89187` |
| — | `simulation_manifest.json` | 5,408 | `13a5e8ee1c3a6114eb3fa99b4bcbe3481926615b3c58ceba4110300a8806c9e0` |

---

## 9. Conclusion & Milestone Sign-Off

Phase 4.1.2.2 establishes an uncompromising mathematical, quantitative, and reproducibility standard for *The Infinite Money Glitch Detector*:
- Point-in-time revision awareness is fully implemented and tested.
- Volatility regimes and calibration sample sizes are derived dynamically without hardcoding.
- Strategy calendar enforcement guarantees valid business settlement.
- Initial simulation conditions are grounded directly in real market quotes.
- Asymptotic claims are replaced by honest finite checkpoint stability disclosures.
- All 368 tests pass across the repository.
- Provenance is fully closed under Stage A snapshot `839e535a724decdc9f6b50061aeef010945ae7fe`.

*Phase 4.1.2.2 is hereby formally closed.*
