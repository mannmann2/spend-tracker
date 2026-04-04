import streamlit as st

from spending_tracker.categorizer import DEFAULT_CATEGORIES
from spending_tracker.db import get_categories, get_uncategorized, init_db, list_merchants, upsert_mapping
from spending_tracker.services import recategorize_uncategorized_transactions
from ui.common import (
    render_badges,
    render_empty_state,
    render_hero,
    render_metrics_row,
    render_section_lead,
    render_shell,
)


init_db()
render_shell(
    "LLM Spending Tracker",
    "Review and update reusable merchant mappings ranked by transaction volume.",
)
render_hero(
    "Mappings",
    "Manage reusable merchant categories from one place. Merchants are ranked by transaction volume so the highest-impact fixes surface first.",
    accent="amber",
)
render_badges(["Reusable mappings", "Merchant triage", "Manual refinement"])


def _format_currency(value: float) -> str:
    return f"{value:,.2f}"


def _save_mapping_from_state(merchant_key: str, widget_key: str) -> None:
    category = st.session_state.get(widget_key)
    if not category:
        return
    upsert_mapping(merchant_key, category)
    st.session_state["mapping_message"] = f"Updated mapping for {merchant_key} -> {category}"


category_options = sorted(set(DEFAULT_CATEGORIES + get_categories()))
uncategorized = get_uncategorized()
merchants = list_merchants()
mapped_merchants = merchants[merchants["has_mapping"] == 1].copy()
unmapped_merchants = merchants[merchants["has_mapping"] == 0].copy()

render_metrics_row(
    [
        ("Mapped Merchants", len(mapped_merchants)),
        ("Unmapped Merchants", len(unmapped_merchants)),
        ("Needs Review", len(uncategorized)),
        ("Known Categories", len(category_options)),
    ]
)

if "mapping_message" in st.session_state:
    st.toast(st.session_state.pop("mapping_message"), icon=":material/check_circle:")

st.subheader("Automation")
render_section_lead("Run the categorisation pass for uncategorised rows, then refine reusable merchant mappings below.")

if st.button("Run LLM Categorisation For Uncategorised Transactions"):
    result = recategorize_uncategorized_transactions()
    if result.updated_count:
        st.success(
            f"Updated {result.updated_count} transactions. {result.remaining_count} still need review."
        )
    if result.error_count:
        st.error(
            f"LLM categorisation failed for {result.error_count} transactions. "
            f"Sample error: {result.sample_error or 'Unknown error'}"
        )
    elif not result.updated_count:
        st.warning("No uncategorised transactions were updated.")
    st.rerun()

tab_mapped, tab_unmapped = st.tabs(["Mapped Merchants", "Needs Mapping"])

with tab_mapped:
    st.write("Update existing merchant mappings. Highest-volume merchants appear first.")
    if mapped_merchants.empty:
        render_empty_state(
            "No merchant mappings yet",
            "Run categorisation or create a mapping from the Needs Mapping tab to start building a reusable library.",
        )
    else:
        for start in range(0, len(mapped_merchants), 3):
            grid = st.columns(3)
            for offset, row in enumerate(mapped_merchants.iloc[start : start + 3].itertuples(index=False)):
                with grid[offset]:
                    card_variant = (start + offset) % 3 + 1
                    st.markdown(
                        f"""
                        <div class="surface-card mapping-card-tight mapping-card-soft-{card_variant}">
                            <div class="mapping-card-header">
                                <h4>{row.sample_description}</h4>
                                <div class="mapping-card-count">{row.transaction_count} txns</div>
                            </div>
                            <p class="surface-meta">
                                Latest {row.latest_txn_date.date()}<br/>
                                Debits {_format_currency(row.debit_total)} | Credits {_format_currency(row.credit_total)}<br/>
                                key: <code>{row.merchant_key}</code>
                            </p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    current_category = row.category if row.category in category_options else None
                    widget_key = f"mapped-category-{row.merchant_key}"
                    st.selectbox(
                        "Mapped category",
                        options=category_options,
                        index=category_options.index(current_category) if current_category else 0,
                        key=widget_key,
                        label_visibility="collapsed",
                        on_change=_save_mapping_from_state,
                        args=(row.merchant_key, widget_key),
                    )

with tab_unmapped:
    st.write("Create mappings for merchants that still fall back to review or non-mapped categorisation.")
    if unmapped_merchants.empty:
        render_empty_state(
            "No merchants need mapping",
            "Every merchant with transactions already has a saved category mapping.",
        )
    else:
        for row in unmapped_merchants.itertuples(index=False):
            with st.container(border=True):
                st.markdown(
                    f'<div class="app-badge-row"><span class="app-badge">Needs Mapping</span><span class="app-badge">{row.transaction_count} txns</span></div>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{row.sample_description}**", help=row.merchant_key)
                st.caption(
                    f"{row.transaction_count} transactions | "
                    f"Latest {row.latest_txn_date.date()} | "
                    f"Current category: {row.category} | "
                    f"key: `{row.merchant_key}`"
                )

                input1, input2 = st.columns([2, 1])
                with input1:
                    use_existing = st.checkbox(
                        "Choose from existing categories",
                        key=f"existing-toggle-{row.merchant_key}",
                        value=True,
                    )

                    if use_existing:
                        widget_key = f"existing-category-{row.merchant_key}"
                        st.selectbox(
                            "Category",
                            options=category_options,
                            index=category_options.index(row.category) if row.category in category_options else 0,
                            key=widget_key,
                            on_change=_save_mapping_from_state,
                            args=(row.merchant_key, widget_key),
                        )
                    else:
                        selected = st.text_input(
                            "New category",
                            key=f"new-category-{row.merchant_key}",
                            placeholder="Enter a category name",
                        )
                        if st.button("Save new category", key=f"save-mapping-{row.merchant_key}", width="stretch"):
                            category = selected.strip()
                            if not category:
                                st.error("Choose or enter a category before saving.")
                            else:
                                upsert_mapping(row.merchant_key, category)
                                st.session_state["mapping_message"] = f"Saved mapping for {row.merchant_key} -> {category}"
                                st.rerun()

                with input2:
                    st.metric("Needs Review Rows", int((uncategorized["merchant_key"] == row.merchant_key).sum()))

st.subheader("Needs Review Transactions")
if uncategorized.empty:
    render_empty_state(
        "No uncategorised transactions",
        "Everything currently has a category, so there is nothing left in the review queue.",
    )
else:
    render_section_lead("These transactions still need attention. Creating a merchant mapping above will update matching rows.")
    preview = uncategorized[["txn_date", "description", "merchant_key", "amount", "direction", "category"]].copy()
    preview["txn_date"] = preview["txn_date"].dt.strftime("%Y-%m-%d")
    st.dataframe(preview, width="stretch", hide_index=True)
