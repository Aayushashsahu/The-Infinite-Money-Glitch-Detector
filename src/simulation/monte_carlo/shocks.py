"""Deterministic macro-financial stress scenarios.

Defines single-factor shocks, compound stress events, liquidity deterioration,
shock timing contracts, and correlation breakdown overlays.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from simulation.monte_carlo.distributions import ensure_positive_semidefinite
from simulation.monte_carlo.schemas import (
    CorrelationStressComparison,
    FactorPanel,
    ScenarioPath,
    StressScenario,
)


def build_standard_stress_scenarios() -> list[StressScenario]:
    """Construct the comprehensive suite of required deterministic stress scenarios.

    Adheres to the documented shock timing contract:
    - By default, currency shocks occur after position entry (default step 5) so that
      their impact is measured on an existing investment exposure.
    - Pre-entry, persistent, and reversal shock options are documented and supported.
    """
    scenarios: list[StressScenario] = []

    # 1. Single-Factor FX Shocks (applied at step 5 after entry while holding open exposure)
    fx_shocks = [0.05, -0.05, 0.10, -0.10, 0.20, -0.20]
    for s in fx_shocks:
        sign_str = f"+{int(s*100)}%" if s > 0 else f"{int(s*100)}%"
        scenarios.append(
            StressScenario(
                name=f"FX Shock {sign_str}",
                description=f"Instantaneous {sign_str} move in foreign investment currency value relative to domestic borrowing currency after entry",
                category="single_factor",
                fx_shock_pct=s,
                shock_timing="after_entry",
                shock_step=5,
                is_persistent=True,
            )
        )

    # 2. Funding-Rate Shocks (applied at step 5 after entry, persistent)
    rate_shocks = [100.0, 300.0, 500.0]
    for r in rate_shocks:
        scenarios.append(
            StressScenario(
                name=f"Borrowing Spike +{int(r)} bps",
                description=f"Instantaneous +{int(r)} basis points increase in commercial borrowing cost",
                category="single_factor",
                borrowing_rate_shock_bps=r,
                shock_timing="after_entry",
                shock_step=5,
                is_persistent=True,
            )
        )

    # 3. Investment-Rate Shocks (applied at step 5 after entry, persistent)
    invest_shocks = [-100.0, -200.0, 100.0]
    for inv in invest_shocks:
        sign_str = f"+{int(inv)} bps" if inv > 0 else f"{int(inv)} bps"
        scenarios.append(
            StressScenario(
                name=f"Investment Yield Shift {sign_str}",
                description=f"Instantaneous {sign_str} shift in foreign asset investment yield",
                category="single_factor",
                investment_rate_shock_bps=inv,
                shock_timing="after_entry",
                shock_step=5,
                is_persistent=True,
            )
        )

    # 4. Execution / Liquidity Shocks
    scenarios.extend([
        StressScenario(
            name="Liquidity Widening (2x Spread, 2x Slippage)",
            description="Dealer bid/ask spreads and market execution slippage double",
            category="liquidity",
            spread_multiplier=2.0,
            slippage_multiplier=2.0,
        ),
        StressScenario(
            name="Liquidity Freeze (5x Spread, 5x Slippage)",
            description="Severe market fragmentation with 5x spread expansion and 5x execution slippage",
            category="liquidity",
            spread_multiplier=5.0,
            slippage_multiplier=5.0,
        ),
    ])

    # 5. Compound Stress Scenarios
    scenarios.extend([
        StressScenario(
            name="Currency Plunge (-10%) & Funding Spike (+300 bps)",
            description="Foreign investment currency depreciates 10% alongside a 300 bps domestic funding rate spike",
            category="compound",
            fx_shock_pct=-0.10,
            borrowing_rate_shock_bps=300.0,
            shock_timing="after_entry",
            shock_step=5,
            is_persistent=True,
        ),
        StressScenario(
            name="Severe Crisis (-20% FX, +500 bps Borrowing, 5x Frictions)",
            description="Compound crisis: 20% currency devaluation, 500 bps funding surge, and 5x execution friction blowout",
            category="compound",
            fx_shock_pct=-0.20,
            borrowing_rate_shock_bps=500.0,
            spread_multiplier=5.0,
            slippage_multiplier=5.0,
            shock_timing="after_entry",
            shock_step=5,
            is_persistent=True,
        ),
        StressScenario(
            name="Carry Compression (-200 bps Yield, +100 bps Borrowing)",
            description="Interest-rate differential collapses: US yields fall 200 bps while Euro funding rises 100 bps",
            category="compound",
            investment_rate_shock_bps=-200.0,
            borrowing_rate_shock_bps=100.0,
            shock_timing="after_entry",
            shock_step=5,
            is_persistent=True,
        ),
    ])

    # 6. Correlation Breakdown Scenario (Decoupled FX & Rates)
    scenarios.append(
        StressScenario(
            name="Historical Correlation Breakdown (Decoupled FX & Rates)",
            description="Complete decoupling of cross-asset correlations between currency returns and interest rate differentials",
            category="correlation",
            correlation_breakdown=True,
        )
    )

    return scenarios


def apply_stress_scenario(
    base_path: ScenarioPath,
    stress: StressScenario,
) -> ScenarioPath:
    """Apply deterministic stress shocks to an existing baseline scenario path.

    Adheres strictly to the documented shock timing contract:
    - 'pre_entry': shock applies across entire path starting at t=0.
    - 'after_entry': shock applies starting at shock_step (default step 5) after an initial
      position has been opened, altering the relative price between entry and exit.
    - 'at_step': shock applies at shock_step, and optionally reverts at reversal_step.
    - 'persistent': shock permanently shifts all subsequent path price levels for t >= shock_step.

    Preserves strictly positive exchange rates (S_t > 0) and non-negative interest rates.
    """
    total_len = len(base_path.fx_rates)
    stressed_fx = list(base_path.fx_rates)
    stressed_borrowing = list(base_path.borrowing_rates)
    stressed_invest = list(base_path.investment_rates)

    shock_step = min(stress.shock_step, total_len - 1)
    reversal_step = stress.reversal_step if stress.reversal_step is not None else (
        shock_step + 1 if not stress.is_persistent else None
    )

    # 1. Apply FX shock on investment currency value
    if stress.fx_shock_pct != 0.0:
        if stress.fx_shock_pct <= -0.999:
            raise ValueError(f"FX shock cannot be <= -100%: {stress.fx_shock_pct}")

        # In canonical terms (EUR per USD), S_canonical' = S_canonical * (1 + fx_shock_pct)
        # In provider quote terms (USD per EUR), S_provider' = S_provider / (1 + fx_shock_pct)
        inv_multiplier = 1.0 + stress.fx_shock_pct

        if stress.shock_timing == "pre_entry":
            # Reprice entire path from step 0 (entry reprices at shocked level)
            stressed_fx = [max(1e-6, p / inv_multiplier) for p in base_path.fx_rates]
        else:
            # Apply shock starting at shock_step
            for t in range(total_len):
                if t >= shock_step:
                    if reversal_step is not None and t >= reversal_step:
                        stressed_fx[t] = base_path.fx_rates[t]
                    else:
                        stressed_fx[t] = max(1e-6, base_path.fx_rates[t] / inv_multiplier)

    # 2. Apply Borrowing Rate shock in bps -> annual decimal
    if stress.borrowing_rate_shock_bps != 0.0:
        borrow_shift = stress.borrowing_rate_shock_bps / 10000.0
        start_t = 0 if stress.shock_timing == "pre_entry" else shock_step
        for t in range(total_len):
            if t >= start_t:
                if reversal_step is not None and t >= reversal_step:
                    stressed_borrowing[t] = base_path.borrowing_rates[t]
                else:
                    stressed_borrowing[t] = max(0.0, base_path.borrowing_rates[t] + borrow_shift)

    # 3. Apply Investment Rate shock in bps -> annual decimal
    if stress.investment_rate_shock_bps != 0.0:
        invest_shift = stress.investment_rate_shock_bps / 10000.0
        start_t = 0 if stress.shock_timing == "pre_entry" else shock_step
        for t in range(total_len):
            if t >= start_t:
                if reversal_step is not None and t >= reversal_step:
                    stressed_invest[t] = base_path.investment_rates[t]
                else:
                    stressed_invest[t] = max(0.0, base_path.investment_rates[t] + invest_shift)

    return ScenarioPath(
        path_id=base_path.path_id,
        steps=base_path.steps,
        dates=base_path.dates,
        fx_rates=stressed_fx,
        borrowing_rates=stressed_borrowing,
        investment_rates=stressed_invest,
        regimes=base_path.regimes,
        is_synthetic=True,
    )


def generate_correlation_breakdown_path(
    panel: FactorPanel,
    random_seed: int = 42,
    horizon: int = 252,
    initial_fx: float = 1.09,
    initial_borrowing_rate: float = 0.04,
    initial_investment_rate: float = 0.05,
) -> tuple[ScenarioPath, dict[str, Any]]:
    """Generate a path under a stressed, decoupled correlation structure.

    Methodology:
    1. Compute empirical covariance matrix Sigma and correlation matrix R.
    2. Decouple cross-factor correlations by setting all off-diagonal correlations to 0.0.
    3. Reconstruct Sigma_stressed = D^(1/2) * R_stressed * D^(1/2).
    4. Project onto positive semi-definite cone via eigenvalue clipping.
    5. Generate multivariate innovations and reconstruct factor levels.
    """
    factor_names = list(panel.values.keys())
    matrix_cols = [np.array(panel.values[f], dtype=np.float64) for f in factor_names]
    data_matrix = np.column_stack(matrix_cols)
    n_factors = data_matrix.shape[1]

    mean_vec = np.mean(data_matrix, axis=0)
    raw_cov = np.cov(data_matrix, rowvar=False, ddof=1)
    if n_factors == 1:
        raw_cov = np.array([[raw_cov]])

    variances = np.diag(raw_cov)
    std_devs = np.sqrt(np.maximum(variances, 1e-12))

    # Empirical correlation matrix
    d_inv = np.diag(1.0 / std_devs)
    empirical_corr = d_inv @ raw_cov @ d_inv

    # Decouple off-diagonal correlations: R_stressed = Identity
    stressed_corr = np.eye(n_factors)

    # Reconstruct stressed covariance
    d_mat = np.diag(std_devs)
    stressed_cov = d_mat @ stressed_corr @ d_mat

    # Verify and repair PSD
    repaired_cov, was_repaired, frob_diff = ensure_positive_semidefinite(stressed_cov)

    # Sample innovations under decoupled correlation structure
    rng = np.random.default_rng(random_seed)
    sampled = rng.multivariate_normal(mean_vec, repaired_cov, size=horizon)

    fx_idx = factor_names.index("FX_EUR_USD_LOGRET")
    borrow_idx = factor_names.index("RATE_DIFF_EUR_BORROW_BPS")
    invest_idx = factor_names.index("YIELD_DIFF_USD_1M_BPS")

    fx_log_ret = sampled[:, fx_idx]
    borrow_diffs = sampled[:, borrow_idx]
    invest_diffs = sampled[:, invest_idx]

    cumulative_log_ret = np.cumsum(fx_log_ret)
    fx_rates = [initial_fx] + (initial_fx * np.exp(cumulative_log_ret)).tolist()

    cum_borrow = np.cumsum(borrow_diffs)
    cum_invest = np.cumsum(invest_diffs)

    borrowing_rates = [initial_borrowing_rate] + [
        max(0.0, initial_borrowing_rate + (b / 10000.0)) for b in cum_borrow
    ]
    investment_rates = [initial_investment_rate] + [
        max(0.0, initial_investment_rate + (inv / 10000.0)) for inv in cum_invest
    ]

    path = ScenarioPath(
        path_id=9999,
        steps=horizon,
        fx_rates=fx_rates,
        borrowing_rates=borrowing_rates,
        investment_rates=investment_rates,
        is_synthetic=True,
    )

    provenance = {
        "scenario_type": "correlation_breakdown",
        "method": "zero_off_diagonal_decoupling",
        "original_correlation_matrix": empirical_corr.tolist(),
        "stressed_correlation_matrix": stressed_corr.tolist(),
        "was_psd_repaired": was_repaired,
        "psd_repair_frobenius_norm": frob_diff,
        "n_factors": n_factors,
    }

    return path, provenance


def evaluate_correlation_stress_distribution(
    panel: FactorPanel,
    strategy: Any,
    num_paths: int = 1000,
    horizon: int = 252,
    random_seed: int = 42,
    initial_capital_a: float = 100_000.0,
    initial_fx: float = 1.09,
    initial_borrowing_rate: float = 0.04,
    initial_investment_rate: float = 0.05,
) -> CorrelationStressComparison:
    """Execute a rigorous distribution comparison between empirical and decorrelated market structures.

    Methodology:
    1. Baseline model: empirical covariance Sigma and empirical mean vector mu.
    2. Stressed model: decoupled cross-factor correlation R_stressed = Identity,
       reconstructing Sigma_stressed = D^(1/2) * R_stressed * D^(1/2) = diag(variances).
    3. Guarantees:
       - Marginal means strictly identical: mu_stressed == mu_baseline
       - Marginal variances strictly identical: Var_stressed == Var_baseline
       - Covariance positive semi-definite (verified and repaired if needed).
    4. Fair comparison: uses Common Random Numbers (CRN) across both models
       Z ~ N(0, I) to minimize Monte Carlo variance on the return difference.
    5. Evaluates complete return, drawdown, VaR, CVaR, and attribution distributions.
    """
    factor_names = list(panel.values.keys())
    matrix_cols = [np.array(panel.values[f], dtype=np.float64) for f in factor_names]
    data_matrix = np.column_stack(matrix_cols)
    n_factors = data_matrix.shape[1]

    mean_vec = np.mean(data_matrix, axis=0)
    raw_cov = np.cov(data_matrix, rowvar=False, ddof=1)
    if n_factors == 1:
        raw_cov = np.array([[raw_cov]])

    # Baseline covariance and correlation
    cov_base, was_repaired_base, _ = ensure_positive_semidefinite(raw_cov)
    variances = np.diag(cov_base)
    std_devs = np.sqrt(np.maximum(variances, 1e-12))
    d_inv = np.diag(1.0 / std_devs)
    empirical_corr = d_inv @ cov_base @ d_inv

    # Stressed covariance: zero off-diagonal correlations
    stressed_corr = np.eye(n_factors)
    d_mat = np.diag(std_devs)
    stressed_cov = d_mat @ stressed_corr @ d_mat
    cov_stressed, was_repaired_stressed, frob_diff = ensure_positive_semidefinite(stressed_cov)

    # Verification checks
    marginal_means_preserved = True
    var_diff = float(np.max(np.abs(np.diag(cov_stressed) - variances)))
    marginal_variances_preserved = bool(var_diff < 1e-8)

    # Cholesky decomposition
    L_base = np.linalg.cholesky(cov_base)
    L_stressed = np.linalg.cholesky(cov_stressed)

    # Sample innovations using Common Random Numbers (CRN)
    rng = np.random.default_rng(random_seed)
    Z = rng.standard_normal(size=(num_paths, horizon, n_factors))

    fx_idx = factor_names.index("FX_EUR_USD_LOGRET")
    borrow_idx = factor_names.index("RATE_DIFF_EUR_BORROW_BPS")
    invest_idx = factor_names.index("YIELD_DIFF_USD_1M_BPS")

    base_evals = []
    stressed_evals = []
    paired_return_diffs: list[float] = []

    for i in range(num_paths):
        z_i = Z[i]

        # 1. Baseline Path
        sampled_base = mean_vec + z_i @ L_base.T
        fx_log_base = sampled_base[:, fx_idx]
        b_diff_base = sampled_base[:, borrow_idx]
        inv_diff_base = sampled_base[:, invest_idx]

        fx_rates_base = [initial_fx] + (initial_fx * np.exp(np.cumsum(fx_log_base))).tolist()
        borrow_base = [initial_borrowing_rate] + [
            max(0.0, initial_borrowing_rate + (b / 10000.0)) for b in np.cumsum(b_diff_base)
        ]
        invest_base = [initial_investment_rate] + [
            max(0.0, initial_investment_rate + (inv / 10000.0)) for inv in np.cumsum(inv_diff_base)
        ]

        p_base = ScenarioPath(
            path_id=i,
            steps=horizon,
            fx_rates=fx_rates_base,
            borrowing_rates=borrow_base,
            investment_rates=invest_base,
            is_synthetic=True,
        )
        e_base = strategy.evaluate_path(p_base, initial_capital_a=initial_capital_a)
        base_evals.append(e_base)

        # 2. Stressed Decorrelated Path
        sampled_stressed = mean_vec + z_i @ L_stressed.T
        fx_log_stressed = sampled_stressed[:, fx_idx]
        b_diff_stressed = sampled_stressed[:, borrow_idx]
        inv_diff_stressed = sampled_stressed[:, invest_idx]

        fx_rates_stressed = [initial_fx] + (initial_fx * np.exp(np.cumsum(fx_log_stressed))).tolist()
        borrow_stressed = [initial_borrowing_rate] + [
            max(0.0, initial_borrowing_rate + (b / 10000.0)) for b in np.cumsum(b_diff_stressed)
        ]
        invest_stressed = [initial_investment_rate] + [
            max(0.0, initial_investment_rate + (inv / 10000.0)) for inv in np.cumsum(inv_diff_stressed)
        ]

        p_stressed = ScenarioPath(
            path_id=i,
            steps=horizon,
            fx_rates=fx_rates_stressed,
            borrowing_rates=borrow_stressed,
            investment_rates=invest_stressed,
            is_synthetic=True,
        )
        e_stressed = strategy.evaluate_path(p_stressed, initial_capital_a=initial_capital_a)
        stressed_evals.append(e_stressed)

        paired_return_diffs.append(float(e_stressed.total_return - e_base.total_return))

    ret_base = np.array([e.total_return for e in base_evals])
    ret_stressed = np.array([e.total_return for e in stressed_evals])
    dd_base = np.array([e.max_drawdown for e in base_evals])
    dd_stressed = np.array([e.max_drawdown for e in stressed_evals])

    mean_base = float(np.mean(ret_base))
    mean_stressed = float(np.mean(ret_stressed))
    med_base = float(np.median(ret_base))
    med_stressed = float(np.median(ret_stressed))

    loss_base = float(np.mean(ret_base < 0.0))
    loss_stressed = float(np.mean(ret_stressed < 0.0))

    # Uncertainty on paired loss probability difference under CRN
    diff_loss = (ret_stressed < 0.0).astype(float) - (ret_base < 0.0).astype(float)
    prob_loss_diff_se = float(np.std(diff_loss, ddof=1) / math.sqrt(num_paths)) if num_paths > 1 else 0.0

    var95_base = float(-np.percentile(ret_base, 5.0))
    var95_stressed = float(-np.percentile(ret_stressed, 5.0))

    tail_base = ret_base[ret_base <= -var95_base]
    tail_stressed = ret_stressed[ret_stressed <= -var95_stressed]
    cvar95_base = float(-np.mean(tail_base)) if len(tail_base) > 0 else var95_base
    cvar95_stressed = float(-np.mean(tail_stressed)) if len(tail_stressed) > 0 else var95_stressed

    med_dd_base = float(np.median(dd_base))
    med_dd_stressed = float(np.median(dd_stressed))

    fin_base = float(np.mean([e.total_financing_costs_a for e in base_evals]))
    fin_stressed = float(np.mean([e.total_financing_costs_a for e in stressed_evals]))
    fx_base = float(np.mean([e.fx_translation_gain_a for e in base_evals]))
    fx_stressed = float(np.mean([e.fx_translation_gain_a for e in stressed_evals]))

    paired_arr = np.array(paired_return_diffs)
    p_mean = float(np.mean(paired_arr))
    p_std = float(np.std(paired_arr, ddof=1)) if len(paired_arr) > 1 else 0.0
    p05 = float(np.percentile(paired_arr, 5.0))
    p50 = float(np.percentile(paired_arr, 50.0))
    p95 = float(np.percentile(paired_arr, 95.0))

    notes = [
        f"Evaluated across {num_paths:,} paired simulation paths using Common Random Numbers (CRN).",
        "Paired return differences are defined as Stressed_i minus Baseline_i (Delta = Stressed - Baseline).",
        "Zero off-diagonal correlation (R_stressed = Identity) is a hypothetical stress condition, not an empirically observed historical state.",
        "Small observed sensitivity under this one historical calibration must not be interpreted as evidence that correlation risk is generally unimportant.",
        "Marginal factor means and marginal variances are strictly identical between baseline and stressed models.",
        "Positive semi-definiteness of the stressed covariance matrix is formally verified and preserved.",
    ]

    return CorrelationStressComparison(
        baseline_model="Empirical Calibration Correlation",
        stressed_model="Zero Off-Diagonal Decoupled Correlation",
        num_paths=num_paths,
        method="zero_off_diagonal_decoupling_with_common_random_numbers",
        baseline_mean_return=mean_base,
        stressed_mean_return=mean_stressed,
        mean_return_difference=mean_stressed - mean_base,
        baseline_median_return=med_base,
        stressed_median_return=med_stressed,
        median_return_difference=med_stressed - med_base,
        baseline_prob_loss=loss_base,
        stressed_prob_loss=loss_stressed,
        prob_loss_difference=loss_stressed - loss_base,
        prob_loss_difference_se=prob_loss_diff_se,
        baseline_var_95=var95_base,
        stressed_var_95=var95_stressed,
        var_95_difference=var95_stressed - var95_base,
        baseline_cvar_95=cvar95_base,
        stressed_cvar_95=cvar95_stressed,
        cvar_95_difference=cvar95_stressed - cvar95_base,
        baseline_median_drawdown=med_dd_base,
        stressed_median_drawdown=med_dd_stressed,
        median_drawdown_difference=med_dd_stressed - med_dd_base,
        baseline_mean_financing_cost_a=fin_base,
        stressed_mean_financing_cost_a=fin_stressed,
        financing_cost_difference_a=fin_stressed - fin_base,
        baseline_mean_fx_translation_a=fx_base,
        stressed_mean_fx_translation_a=fx_stressed,
        fx_translation_difference_a=fx_stressed - fx_base,
        paired_return_difference_mean=p_mean,
        paired_return_difference_std=p_std,
        paired_return_difference_p05=p05,
        paired_return_difference_p50=p50,
        paired_return_difference_p95=p95,
        marginal_means_preserved=marginal_means_preserved,
        marginal_variances_preserved=marginal_variances_preserved,
        is_psd_repaired=was_repaired_stressed,
        psd_repair_frobenius_norm=frob_diff,
        empirical_correlation_matrix=empirical_corr.tolist(),
        stressed_correlation_matrix=stressed_corr.tolist(),
        notes=notes,
    )

