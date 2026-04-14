import streamlit as st

from ui.common import render_empty_state, render_metrics_row


def format_currency(value: float) -> str:
    return f"{value:,.2f}"


def render_statement_transactions(statement_transactions, statement_id: int) -> None:
    transactions = statement_transactions[
        statement_transactions["statement_id"] == statement_id
    ].copy()
    if transactions.empty:
        render_empty_state(
            "No transactions stored for this statement",
            "The statement record exists, but no parsed transactions were saved for it.",
        )
        return

    display = transactions[
        [
            "txn_date",
            "description",
            "category",
            "direction",
            "amount",
            "source",
            "confidence",
        ]
    ].copy()
    display["txn_date"] = display["txn_date"].dt.strftime("%Y-%m-%d")
    st.dataframe(display, width="stretch", hide_index=True)


def render_statement_library(
    statements,
    statement_transactions,
    on_delete_selected,
    on_delete_all,
) -> None:
    if statements.empty:
        render_empty_state(
            "No statements uploaded yet",
            "Use the upload form above to add your first statement and populate the library.",
        )
        return

    if "selected_statement_id" not in st.session_state:
        st.session_state["selected_statement_id"] = int(statements.iloc[0]["id"])

    valid_ids = statements["id"].astype(int).tolist()
    if st.session_state["selected_statement_id"] not in valid_ids:
        st.session_state["selected_statement_id"] = valid_ids[0]

    library_col, detail_col = st.columns([0.75, 1.75], vertical_alignment="top")

    with library_col:
        for row in statements.itertuples(index=False):
            label = f"{row.file_name} · {row.account}"
            if st.button(
                label,
                key=f"select-statement-{row.id}",
                type="primary"
                if int(row.id) == st.session_state["selected_statement_id"]
                else "secondary",
                width="stretch",
            ):
                st.session_state["selected_statement_id"] = int(row.id)
                st.rerun()

    selected_id = int(st.session_state["selected_statement_id"])
    selected_row = statements[statements["id"] == selected_id].iloc[0]
    selected_transactions = statement_transactions[
        statement_transactions["statement_id"] == selected_id
    ]

    with detail_col:
        st.markdown(
            f"""
            <div class="surface-card">
                <h4>{selected_row.file_name}</h4>
                <div class="surface-meta">
                    {selected_row.account} | Uploaded {selected_row.uploaded_at}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if selected_transactions.empty:
            render_metrics_row(
                [("Transactions", 0), ("Debits", "0.00"), ("Credits", "0.00"), ("Needs Review", 0)]
            )
        else:
            debit_total = selected_transactions.loc[
                selected_transactions["direction"] == "debit", "amount"
            ].sum()
            credit_total = selected_transactions.loc[
                selected_transactions["direction"] == "credit", "amount"
            ].sum()
            render_metrics_row(
                [
                    ("Transactions", int(selected_row.transaction_count)),
                    ("Debits", format_currency(debit_total)),
                    ("Credits", format_currency(credit_total)),
                    (
                        "Needs Review",
                        int((selected_transactions["category"] == "Needs Review").sum()),
                    ),
                ]
            )

        action1, action2 = st.columns([1, 1])
        if action1.button(
            "Delete Selected Statement", key=f"delete-statement-{selected_id}", width="stretch"
        ):
            on_delete_selected(selected_id, selected_row.file_name)
        if action2.button("Delete All Uploaded Statements", type="secondary", width="stretch"):
            on_delete_all()

        with st.expander("View extracted transactions", expanded=True):
            render_statement_transactions(statement_transactions, selected_id)
