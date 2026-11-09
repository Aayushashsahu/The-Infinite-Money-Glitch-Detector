"""Double-Entry P&L Attribution Waterfall Plot Component for Phase 5 Dashboard.

Builds a mathematically exact, reconciled waterfall chart illustrating the
cross-currency carry trade P&L components from Config 2 (Estimated Schedule).
"""

from __future__ import annotations

import plotly.graph_objects as go

from dashboard.artifacts.schemas import BacktestAttributionSchema
from dashboard.components.metrics_card import format_currency
from dashboard.components.plots.base import PALETTE, apply_institutional_theme


def build_attribution_waterfall_figure(
    attr: BacktestAttributionSchema,
    height: int = 460,
) -> go.Figure:
    """Build a Plotly waterfall figure visualizing double-entry carry trade P&L attribution.

    Mathematical Decomposition:
        Investment Yield (+€5,437.03)
      + FX Translation Loss (-€5,655.77)
      - Financing Borrowing Costs (-€3,683.87)
      + Cash Deposit Interest (+€7,702.87)
      - Transaction Frictions (-€910.04)
      = Net Realized Profit (+€2,890.22)
    """
    yield_gain = attr.investment_yield_gain_a
    fx_loss = attr.fx_translation_gain_a  # Negative (-5655.77)
    financing_drag = -attr.total_financing_costs_a  # Cost entered as negative (-3683.87)
    cash_interest = attr.total_cash_interest_a  # Positive (+7702.87)
    frictions_drag = -attr.total_frictions_a  # Drag entered as negative (-910.04)
    net_profit = yield_gain + fx_loss + financing_drag + cash_interest + frictions_drag

    x_labels = [
        "Investment Yield",
        "FX Translation",
        "Financing Costs",
        "Cash Interest",
        "Frictions",
        "Net Profit",
    ]
    y_values = [
        yield_gain,
        fx_loss,
        financing_drag,
        cash_interest,
        frictions_drag,
        net_profit,
    ]
    measures = ["relative", "relative", "relative", "relative", "relative", "total"]
    text_labels = [format_currency(v) for v in y_values]

    fig = go.Figure(
        go.Waterfall(
            name="P&L Attribution",
            orientation="v",
            measure=measures,
            x=x_labels,
            textposition="outside",
            text=text_labels,
            y=y_values,
            connector={"line": {"color": PALETTE["zero_line"], "width": 1.2}},
            increasing={"marker": {"color": PALETTE["profit"]}},
            decreasing={"marker": {"color": PALETTE["loss"]}},
            totals={"marker": {"color": PALETTE["primary"]}},
            hovertemplate=("<b>%{x}</b><br>Impact: %{y:,.2f} EUR<br><extra></extra>"),
        )
    )

    apply_institutional_theme(
        fig,
        title="Double-Entry P&L Attribution Waterfall (EUR)",
        x_title="Attribution Factor",
        y_title="P&L Contribution (EUR)",
        height=height,
        show_legend=False,
    )
    return fig
