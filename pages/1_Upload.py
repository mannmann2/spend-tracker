import streamlit as st

from spending_tracker.db import (
    delete_all_statements,
    delete_statement,
    init_db,
    list_statement_transactions,
    list_statements,
)
from spending_tracker.services import ingest_statement
from ui.common import (
    render_badges,
    render_hero,
    render_metrics_row,
    render_section_lead,
    render_shell,
)
from ui.upload import render_statement_library

ACCOUNT_OPTIONS = ["Amex", "Chase", "Chase Credit"]


init_db()
render_shell(
    "LLM Spending Tracker",
    "Upload statements, correct categories, and analyse spend across accounts over time.",
)
render_hero(
    "Statement Intake",
    "Upload one or more PDF bank statements, monitor parser diagnostics, and inspect the transactions already extracted from prior uploads grouped by statement.",
    accent="sky",
)
render_badges(["PDF ingestion", "Statement diagnostics", "Library browser"])

for message_type, message in st.session_state.get("upload_messages", []):
    getattr(st, message_type)(message)
st.session_state.pop("upload_messages", None)

for debug in st.session_state.get("upload_debug", []):
    with st.expander(f"Parsing debug: {debug['file_name']}", expanded=debug["parsed_count"] == 0):
        st.write(f"Parser used: `{debug['parser_used']}`")
        st.write(f"Detected text lines: `{debug['line_count']}`")
        st.write(f"Transactions found: `{debug['parsed_count']}`")
        st.write(f"LLM attempted: `{debug['llm_attempted']}`")
        st.write(f"LLM succeeded: `{debug['llm_succeeded']}`")
        if debug["warnings"]:
            for warning in debug["warnings"]:
                st.warning(warning)
        st.text_area(
            "Extracted text preview",
            value=debug["text_preview"],
            height=260,
            key=f"debug-preview-{debug['file_name']}",
        )
st.session_state.pop("upload_debug", None)

statements = list_statements()
statement_transactions = list_statement_transactions()


def _delete_selected_statement(statement_id: int, file_name: str) -> None:
    deleted = delete_statement(statement_id)
    if deleted:
        st.session_state["upload_messages"] = [
            ("success", f"Deleted uploaded statement: {file_name}")
        ]
    else:
        st.session_state["upload_messages"] = [
            ("warning", f"Statement already removed: {file_name}")
        ]
    st.rerun()


def _delete_all_statements() -> None:
    deleted_count = delete_all_statements()
    st.session_state["upload_messages"] = [
        ("success", f"Deleted {deleted_count} uploaded statements.")
    ]
    st.rerun()


total_statements = len(statements)
total_transactions = (
    int(statement_transactions["id"].count()) if not statement_transactions.empty else 0
)
accounts_covered = int(statements["account"].nunique()) if not statements.empty else 0
needs_review = (
    int((statement_transactions["category"] == "Needs Review").sum())
    if not statement_transactions.empty
    else 0
)

render_metrics_row(
    [
        ("Uploaded Statements", total_statements),
        ("Extracted Transactions", total_transactions),
        ("Accounts Covered", accounts_covered),
        ("Needs Review", needs_review),
    ]
)

st.subheader("Upload")
render_section_lead(
    "Drag and drop one or more PDF bank statements. Newly uploaded files are parsed and reflected immediately."
)

with st.container():
    st.caption(
        "Amex and Chase Credit uploads automatically skip page 1 and the last 3 pages before extraction."
    )
    with st.form("upload-form", clear_on_submit=True):
        account_name = st.selectbox("Bank account", options=ACCOUNT_OPTIONS, index=0)
        files = st.file_uploader("PDF statements", type=["pdf"], accept_multiple_files=True)
        submitted = st.form_submit_button("Process statements", type="primary", width="stretch")

if submitted:
    if not files:
        st.error("Upload at least one PDF statement.")
    else:
        messages: list[tuple[str, str]] = []
        debug_payload: list[dict] = []
        for file in files:
            result = ingest_statement(file, account_name)
            parsed_count = result.parsed_count
            inserted_count = result.inserted_count
            if inserted_count:
                messages.append(
                    (
                        "success",
                        f"{file.name}: {result.message} Inserted {inserted_count} transactions.",
                    )
                )
            else:
                messages.append(("info", f"{file.name}: {result.message}"))
            if parsed_count == 0:
                messages.append(
                    (
                        "warning",
                        f"{file.name}: No transactions were detected. Review the parsing debug panel below.",
                    )
                )
            debug_payload.append(
                {
                    "file_name": file.name,
                    "parser_used": result.diagnostics.parser_used,
                    "line_count": result.diagnostics.line_count,
                    "parsed_count": parsed_count,
                    "llm_attempted": result.diagnostics.llm_attempted,
                    "llm_succeeded": result.diagnostics.llm_succeeded,
                    "warnings": result.diagnostics.warnings,
                    "text_preview": result.diagnostics.text_preview,
                }
            )
        st.session_state["upload_messages"] = messages
        st.session_state["upload_debug"] = debug_payload
        st.rerun()

st.subheader("Statement Library")
render_section_lead(
    "Browse previous uploads, use the list as a quick selector, and inspect extracted transactions for the selected statement in the detail panel."
)
render_statement_library(
    statements=statements,
    statement_transactions=statement_transactions,
    on_delete_selected=_delete_selected_statement,
    on_delete_all=_delete_all_statements,
)
