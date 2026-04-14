import logging
from datetime import date

import streamlit as st

from spending_tracker.analytics import filter_transactions
from spending_tracker.db import get_accounts


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        root_logger.setLevel(logging.INFO)


def init_app(page_title: str, page_icon: str = "💳") -> None:
    configure_logging()
    st.set_page_config(page_title=page_title, page_icon=page_icon, layout="wide")
    inject_base_styles()


def inject_base_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --app-ink: #0f172a;
            --app-muted: #475569;
            --app-border: rgba(15, 23, 42, 0.08);
            --app-shadow: 0 14px 36px rgba(15, 23, 42, 0.06);
            --app-surface: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.94));
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(14, 165, 233, 0.05), transparent 28%),
                radial-gradient(circle at top right, rgba(251, 191, 36, 0.05), transparent 24%),
                linear-gradient(180deg, #f8fafc 0%, #ffffff 24%, #f8fafc 100%);
        }
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }
        .stSidebar > div:first-child {
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(248, 250, 252, 0.98));
        }
        [data-testid="stMetric"] {
            background: var(--app-surface);
            border: 1px solid var(--app-border);
            border-radius: 18px;
            padding: 0.9rem 1rem;
            box-shadow: var(--app-shadow);
        }
        div[data-testid="stExpander"] {
            border: 1px solid var(--app-border);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.9);
            box-shadow: var(--app-shadow);
        }
        div[data-testid="stForm"] {
            border-radius: 20px;
        }
        div[data-testid="stVerticalBlock"] div[data-testid="stTabs"] button {
            border-radius: 999px;
        }
        .app-hero {
            padding: 1.45rem 1.55rem;
            border: 1px solid var(--app-border);
            border-radius: 24px;
            box-shadow: var(--app-shadow);
            margin: 0.75rem 0 1.1rem 0;
        }
        .app-hero h2 {
            margin: 0 0 0.35rem 0;
            font-size: 1.7rem;
            color: var(--app-ink);
            letter-spacing: -0.02em;
        }
        .app-hero p {
            margin: 0;
            color: #334155;
            max-width: 58rem;
            line-height: 1.55;
        }
        .app-hero--sky {
            background:
                radial-gradient(circle at top right, rgba(14, 165, 233, 0.18), transparent 28%),
                linear-gradient(135deg, rgba(248, 250, 252, 0.98), rgba(239, 246, 255, 0.96));
        }
        .app-hero--amber {
            background:
                radial-gradient(circle at top left, rgba(251, 191, 36, 0.18), transparent 28%),
                linear-gradient(135deg, rgba(255, 251, 235, 0.98), rgba(248, 250, 252, 0.96));
        }
        .app-hero--coral {
            background:
                radial-gradient(circle at top right, rgba(249, 115, 22, 0.16), transparent 28%),
                linear-gradient(135deg, rgba(255, 247, 237, 0.98), rgba(254, 242, 242, 0.96));
        }
        .surface-card {
            padding: 1rem 1.1rem;
            border: 1px solid var(--app-border);
            border-radius: 18px;
            background: var(--app-surface);
            box-shadow: var(--app-shadow);
            margin-bottom: 0.9rem;
        }
        .surface-card h4 {
            margin: 0 0 0.2rem 0;
            font-size: 1.02rem;
            color: var(--app-ink);
        }
        .surface-meta {
            color: var(--app-muted);
            font-size: 0.92rem;
            line-height: 1.5;
        }
        .mapping-card-tight {
            padding: 0.85rem 0.95rem;
            margin-bottom: 0.55rem;
        }
        .mapping-card-soft-1 {
            background:
                radial-gradient(circle at top right, rgba(14, 165, 233, 0.08), transparent 32%),
                linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.94));
        }
        .mapping-card-soft-2 {
            background:
                radial-gradient(circle at top right, rgba(251, 191, 36, 0.08), transparent 32%),
                linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 251, 235, 0.94));
        }
        .mapping-card-soft-3 {
            background:
                radial-gradient(circle at top right, rgba(34, 197, 94, 0.07), transparent 32%),
                linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(240, 253, 244, 0.94));
        }
        .mapping-card-header {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 0.75rem;
        }
        .mapping-card-count {
            font-size: 0.84rem;
            font-weight: 700;
            color: #0f172a;
            white-space: nowrap;
        }
        .mapping-card-tight .surface-meta {
            font-size: 0.84rem;
            line-height: 1.4;
        }
        .app-badge-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin: 0 0 0.7rem 0;
        }
        .app-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.28rem 0.58rem;
            border-radius: 999px;
            border: 1px solid rgba(15, 23, 42, 0.08);
            background: rgba(255, 255, 255, 0.85);
            color: var(--app-ink);
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.01em;
        }
        .empty-state {
            border: 1px dashed rgba(15, 23, 42, 0.16);
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.82);
            padding: 1.15rem 1.2rem;
            color: var(--app-muted);
            margin: 0.55rem 0 0.95rem 0;
        }
        .empty-state strong {
            display: block;
            color: var(--app-ink);
            margin-bottom: 0.28rem;
        }
        .section-lead {
            margin: -0.15rem 0 0.9rem 0;
            color: #475569;
            line-height: 1.5;
            max-width: 60rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_shell(title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)


def render_hero(title: str, description: str, accent: str = "sky") -> None:
    st.markdown(
        f"""
        <div class="app-hero app-hero--{accent}">
            <h2>{title}</h2>
            <p>{description}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_lead(text: str) -> None:
    st.markdown(f'<p class="section-lead">{text}</p>', unsafe_allow_html=True)


def render_badges(items: list[str]) -> None:
    if not items:
        return
    badges = "".join(f'<span class="app-badge">{item}</span>' for item in items)
    st.markdown(f'<div class="app-badge-row">{badges}</div>', unsafe_allow_html=True)


def render_metrics_row(
    metrics: list[tuple[str, str | int | float]], columns: int | None = None
) -> None:
    if not metrics:
        return
    column_count = columns or len(metrics)
    grid = st.columns(column_count)
    for index, (label, value) in enumerate(metrics):
        grid[index % column_count].metric(label, value)


def render_empty_state(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="empty-state">
            <strong>{title}</strong>
            <span>{body}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_filters_sidebar(df):
    st.sidebar.header("Filters")
    min_date = df["txn_date"].dt.date.min() if not df.empty else date.today()
    max_date = df["txn_date"].dt.date.max() if not df.empty else date.today()

    start_date = st.sidebar.date_input(
        "Start date", value=min_date, min_value=min_date, max_value=max_date
    )
    end_date = st.sidebar.date_input(
        "End date", value=max_date, min_value=min_date, max_value=max_date
    )
    include_transfers = st.sidebar.toggle("Show transfers", value=False)
    categories = st.sidebar.multiselect(
        "Categories",
        options=sorted(df["category"].unique()) if not df.empty else [],
    )
    accounts = st.sidebar.multiselect("Accounts", options=get_accounts())
    directions = st.sidebar.multiselect(
        "Direction", options=["debit", "credit"], default=["debit", "credit"]
    )

    filtered = filter_transactions(
        df,
        start_date,
        end_date,
        categories,
        accounts,
        directions,
        include_transfers=include_transfers,
    )
    return filtered
