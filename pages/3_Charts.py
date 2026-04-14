import pandas as pd
import plotly.express as px
import streamlit as st

from spending_tracker.analytics import aggregate_transactions
from spending_tracker.db import init_db, load_transactions
from ui.common import (
    render_badges,
    render_empty_state,
    render_filters_sidebar,
    render_hero,
    render_metrics_row,
    render_section_lead,
    render_shell,
)

CUMULATIVE_COLOR_SEQUENCE = [
    "#0F766E",
    "#2563EB",
    "#DC2626",
    "#7C3AED",
    "#D97706",
    "#059669",
    "#DB2777",
    "#4F46E5",
    "#0891B2",
    "#EA580C",
    "#65A30D",
    "#BE123C",
    "#7E22CE",
    "#1D4ED8",
    "#0369A1",
    "#C2410C",
    "#9333EA",
    "#0D9488",
    "#CA8A04",
    "#E11D48",
]


init_db()
render_shell(
    "LLM Spending Tracker",
    "Visualise spending trends over time across categories and accounts.",
)
render_hero(
    "Charts",
    "Follow cumulative spend, monthly category mix, and account intensity with the same active filters used across the rest of the app.",
    accent="coral",
)
render_badges(["Trend analysis", "Category mix", "Account intensity"])

data = load_transactions()
filtered = render_filters_sidebar(data)

st.subheader("Visualisations")
render_section_lead(
    "Charts respond to the sidebar filters, so you can narrow accounts, dates, categories, directions, and transfers before comparing trends."
)
if filtered.empty:
    render_empty_state(
        "No data available for charts",
        "Upload statements or relax the active filters to start exploring the visualisations.",
    )
else:
    expenses = filtered[filtered["direction"] == "debit"].copy()
    if expenses.empty:
        render_empty_state(
            "No expense transactions in view",
            "The current filter combination only includes credits or excludes all debit transactions.",
        )
    else:
        render_metrics_row(
            [
                ("Expense Rows", len(expenses)),
                ("Filtered Spend", f"{expenses['amount'].sum():,.2f}"),
                ("Categories", expenses["category"].nunique()),
            ]
        )

        monthly = aggregate_transactions(expenses, ["month", "category"])
        monthly["amount"] = monthly["amount"].abs()
        monthly["month_label"] = pd.to_datetime(monthly["month"] + "-01").dt.strftime("%b %Y")
        category_order = (
            expenses.groupby("category", dropna=False)["amount"]
            .sum()
            .sort_values(ascending=False)
            .index.astype(str)
            .tolist()
        )
        monthly["category"] = monthly["category"].astype(str)
        trend = px.bar(
            monthly,
            x="month_label",
            y="amount",
            color="category",
            title="Monthly spend by category",
            category_orders={"category": category_order},
        )
        trend.update_layout(
            barmode="stack",
            xaxis_title="Month",
            yaxis_title="Spend",
            height=560,
            legend_title_text="Category",
        )

        account_mix = (
            expenses.groupby(["account", "category"], dropna=False)["amount"].sum().reset_index()
        )
        heatmap = px.density_heatmap(
            account_mix,
            x="account",
            y="category",
            z="amount",
            title="Account/category intensity",
            text_auto=True,
        )
        heatmap.update_layout(height=560)

        available_years = sorted(expenses["year"].dropna().unique().tolist())
        selected_year = st.selectbox(
            "Year for cumulative daily category spend",
            options=available_years,
            index=len(available_years) - 1,
        )
        year_expenses = expenses[expenses["year"] == selected_year].copy()

        cumulative_daily = (
            year_expenses.groupby(["txn_date", "category"], dropna=False)["amount"]
            .sum()
            .reset_index()
            .sort_values(["category", "txn_date"])
        )
        cumulative_daily["cumulative_spend"] = cumulative_daily.groupby("category")[
            "amount"
        ].cumsum()

        latest_txn_date = year_expenses["txn_date"].max().normalize()
        date_range = pd.date_range(
            start=f"{selected_year}-01-01",
            end=latest_txn_date,
            freq="D",
        )
        categories = sorted(cumulative_daily["category"].astype(str).unique().tolist())
        complete_index = pd.MultiIndex.from_product(
            [date_range, categories],
            names=["txn_date", "category"],
        )
        cumulative_daily["category"] = cumulative_daily["category"].astype(str)
        cumulative_daily = (
            cumulative_daily.set_index(["txn_date", "category"])[["cumulative_spend"]]
            .reindex(complete_index)
            .groupby(level="category")
            .ffill()
            .fillna(0)
            .reset_index()
        )
        cumulative_chart = px.line(
            cumulative_daily,
            x="txn_date",
            y="cumulative_spend",
            color="category",
            title=f"Cumulative daily spend by category for {selected_year}",
            color_discrete_sequence=CUMULATIVE_COLOR_SEQUENCE,
        )
        cumulative_chart.update_layout(
            xaxis_title="Day",
            yaxis_title="Cumulative spend",
            height=640,
        )
        cumulative_chart.update_traces(line={"width": 3.5})

        st.subheader("Trends")
        render_section_lead(
            "Track cumulative spending over the year and compare how categories stack month by month."
        )
        st.plotly_chart(cumulative_chart, width="stretch")
        st.plotly_chart(trend, width="stretch")

        st.subheader("Breakdowns")
        render_section_lead(
            "Switch period controls to isolate category concentration for a specific month or year."
        )
        category_period = st.radio(
            "Category spend period",
            options=["Month", "Year"],
            index=1,
            horizontal=True,
        )
        if category_period == "Month":
            available_months = sorted(expenses["month"].dropna().unique().tolist())
            selected_month = st.selectbox(
                "Month for category spend",
                options=available_months,
                index=len(available_months) - 1,
                format_func=lambda value: pd.to_datetime(f"{value}-01").strftime("%B %Y"),
            )
            breakdown_source = expenses[expenses["month"] == selected_month].copy()
            breakdown_title = f"Category spend breakdown for {pd.to_datetime(f'{selected_month}-01').strftime('%B %Y')}"
        else:
            available_breakdown_years = sorted(expenses["year"].dropna().unique().tolist())
            selected_breakdown_year = st.selectbox(
                "Year for category spend",
                options=available_breakdown_years,
                index=len(available_breakdown_years) - 1,
            )
            breakdown_source = expenses[expenses["year"] == selected_breakdown_year].copy()
            breakdown_title = f"Category spend breakdown for {selected_breakdown_year}"

        category_totals = (
            breakdown_source.groupby("category", dropna=False)["amount"]
            .sum()
            .reset_index()
            .sort_values("amount", ascending=False)
        )
        category_totals["category"] = category_totals["category"].astype(str)
        breakdown = px.bar(
            category_totals,
            x="category",
            y="amount",
            color="category",
            title=breakdown_title,
            category_orders={"category": category_order},
        )
        breakdown.update_layout(height=560, legend_title_text="Category")
        st.plotly_chart(breakdown, width="stretch")

        st.subheader("Mix")
        render_section_lead(
            "Use the heatmap to spot which accounts dominate each spending category."
        )
        st.plotly_chart(heatmap, width="stretch")
