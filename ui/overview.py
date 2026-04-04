import html

import pandas as pd
import streamlit as st

from spending_tracker.analytics import aggregate_transactions
from ui.common import (
    render_badges,
    render_empty_state,
    render_filters_sidebar,
    render_hero,
    render_metrics_row,
    render_section_lead,
    render_shell,
)


def _format_currency(value: float) -> str:
    return f"{value:,.2f}"


def _inject_overview_styles() -> None:
    st.markdown(
        """
        <style>
        .overview-card {
            position: relative;
            padding: 1rem 1.05rem;
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 20px;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.06);
            min-height: 126px;
            overflow: visible;
        }
        .overview-card-top {
            display: flex;
            justify-content: flex-end;
            margin-bottom: 0.2rem;
        }
        .overview-card-tooltip {
            position: absolute;
            left: 0;
            right: 0;
            bottom: calc(100% + 0.6rem);
            background: rgba(15, 23, 42, 0.96);
            color: #f8fafc;
            border-radius: 14px;
            padding: 0.75rem 0.85rem;
            font-size: 0.8rem;
            line-height: 1.45;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.22);
            opacity: 0;
            transform: translateY(6px);
            pointer-events: none;
            transition: opacity 140ms ease, transform 140ms ease;
            z-index: 30;
            white-space: pre-line;
        }
        .overview-card:hover .overview-card-tooltip {
            opacity: 1;
            transform: translateY(0);
        }
        .overview-card-badge {
            display: inline-flex;
            align-items: center;
            padding: 0.2rem 0.5rem;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid rgba(15, 23, 42, 0.08);
            font-size: 0.72rem;
            font-weight: 600;
            color: #334155;
        }
        .overview-card-value {
            font-size: 1.72rem;
            font-weight: 700;
            color: #0f172a;
            line-height: 1.15;
            margin-bottom: 0.28rem;
        }
        .overview-card-meta {
            font-size: 0.82rem;
            color: #475569;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _card_gradient(index: int) -> str:
    gradients = [
        "radial-gradient(circle at top right, rgba(14, 165, 233, 0.22), transparent 30%), linear-gradient(135deg, rgba(248, 250, 252, 0.98), rgba(239, 246, 255, 0.96))",
        "radial-gradient(circle at top right, rgba(34, 197, 94, 0.2), transparent 30%), linear-gradient(135deg, rgba(240, 253, 244, 0.98), rgba(236, 253, 245, 0.94))",
        "radial-gradient(circle at top right, rgba(249, 115, 22, 0.2), transparent 30%), linear-gradient(135deg, rgba(255, 247, 237, 0.98), rgba(255, 237, 213, 0.94))",
        "radial-gradient(circle at top right, rgba(236, 72, 153, 0.18), transparent 30%), linear-gradient(135deg, rgba(253, 242, 248, 0.98), rgba(252, 231, 243, 0.94))",
        "radial-gradient(circle at top right, rgba(168, 85, 247, 0.18), transparent 30%), linear-gradient(135deg, rgba(245, 243, 255, 0.98), rgba(237, 233, 254, 0.94))",
        "radial-gradient(circle at top right, rgba(245, 158, 11, 0.2), transparent 30%), linear-gradient(135deg, rgba(255, 251, 235, 0.98), rgba(254, 243, 199, 0.94))",
    ]
    return gradients[index % len(gradients)]


def _render_spending_cards(aggregated: pd.DataFrame, secondary_label: str) -> None:
    rows = aggregated.reset_index(drop=True)
    cards_per_row = min(4, max(1, len(rows)))

    for start in range(0, len(rows), cards_per_row):
        columns = st.columns(cards_per_row)
        for offset, (_, row) in enumerate(rows.iloc[start : start + cards_per_row].iterrows()):
            index = start + offset
            with columns[offset]:
                tooltip = html.escape(str(row["Tooltip"]))
                st.markdown(
                    (
                        f'<div class="overview-card" style="background: {_card_gradient(index)};">'
                        f'<div class="overview-card-tooltip">{tooltip}</div>'
                        f'<div class="overview-card-top"><div class="overview-card-badge">{row["Label"]}</div></div>'
                        f'<div class="overview-card-value">{_format_currency(float(row["Spend"]))}</div>'
                        f'<div class="overview-card-meta">{secondary_label}: {float(row["Share"]):.1f}% of filtered spend</div>'
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )


def _render_spending_aggregation(expenses: pd.DataFrame) -> None:
    if expenses.empty:
        st.info("No spending transactions available in the current filter selection.")
        return

    grouping_options = ["category", "account", "month", "year", "direction", "day"]
    group_by = st.multiselect(
        "Group by",
        options=grouping_options,
        default=["month", "category"],
        help="Combine one or more fields to change how spend is grouped into cards.",
    )
    if not group_by:
        st.warning("Select at least one aggregation dimension.")
        return

    aggregated = aggregate_transactions(expenses, group_by).rename(columns={"amount": "Spend"})
    aggregated["Spend"] = aggregated["Spend"].abs()
    aggregated["Label"] = aggregated[group_by].astype(str).agg(" | ".join, axis=1)
    aggregated = aggregated.sort_values("Spend", ascending=False).reset_index(drop=True)
    total_spend = float(aggregated["Spend"].sum())
    aggregated["Share"] = 0.0 if total_spend == 0 else (aggregated["Spend"] / total_spend) * 100

    tooltips: list[str] = []
    for row in aggregated[group_by].to_dict("records"):
        matches = expenses.copy()
        for field, value in row.items():
            matches = matches[matches[field] == value]

        top_matches = (
            matches.sort_values(["amount", "txn_date"], ascending=[False, False])
            .head(3)
            .loc[:, ["txn_date", "description", "amount"]]
            .copy()
        )
        if top_matches.empty:
            tooltips.append("No transactions in this group.")
            continue

        top_matches["txn_date"] = top_matches["txn_date"].dt.strftime("%Y-%m-%d")
        tooltips.append(
            "Top transactions:\n"
            + "\n".join(
                f"{txn.txn_date} | {txn.description} | {_format_currency(float(txn.amount))}"
                for txn in top_matches.itertuples(index=False)
            )
        )
    aggregated["Tooltip"] = tooltips

    _render_spending_cards(aggregated[["Label", "Spend", "Share", "Tooltip"]], "Share")


def render_overview_page(data: pd.DataFrame) -> None:
    render_shell(
        "LLM Spending Tracker",
        "Review filtered transactions and aggregated spending as soon as the app opens.",
    )
    render_hero(
        "Overview",
        "Explore filtered spending, regroup transactions dynamically, and inspect the raw ledger only when you need to drop to detail.",
        accent="sky",
    )
    render_badges(["Live filters", "Grouped cards", "Drill-down table"])
    _inject_overview_styles()
    filtered = render_filters_sidebar(data)

    if filtered.empty:
        if data.empty:
            render_empty_state(
                "No transactions available yet",
                "Upload a statement to start building your transaction history and grouped spend view.",
            )
        else:
            render_empty_state(
                "No transactions match the current filters",
                "Relax the sidebar filters or include transfers to bring rows back into view.",
            )
        return

    expenses = filtered[filtered["direction"] == "debit"].copy()
    income = filtered[filtered["direction"] == "credit"].copy()

    render_metrics_row(
        [
            ("Transactions", len(filtered)),
            ("Total Spend", _format_currency(float(expenses["amount"].sum()))),
            ("Total Income", _format_currency(float(income["amount"].sum()))),
        ]
    )

    st.subheader("Grouped Spend")
    render_section_lead("Pick one or more dimensions below to reshape the spend cards without changing the active sidebar filters.")
    _render_spending_aggregation(expenses)

    st.markdown("<div style='height: 1.25rem;'></div>", unsafe_allow_html=True)

    with st.expander("Raw Transactions", expanded=False):
        display = filtered[
            [
                "txn_date",
                "account",
                "description",
                "category",
                "direction",
                "amount",
                "source",
                "confidence",
            ]
        ].copy()
        display = display.sort_values("txn_date", ascending=True).reset_index(drop=True)
        display["txn_date"] = display["txn_date"].dt.strftime("%Y-%m-%d")
        st.dataframe(display, width="stretch", hide_index=True)
