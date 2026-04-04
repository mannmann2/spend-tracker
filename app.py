import streamlit as st

from spending_tracker.db import init_db, load_transactions
from ui.common import init_app
from ui.overview import render_overview_page


def _overview_page() -> None:
    init_db()
    data = load_transactions()
    render_overview_page(data)


init_app("LLM Spending Tracker")
navigation = st.navigation(
    [
        st.Page(_overview_page, title="Overview", icon=":material/home:", default=True),
        st.Page("pages/1_Upload.py", title="Upload", icon=":material/upload_file:"),
        st.Page("pages/2_Mappings.py", title="Mappings", icon=":material/category:"),
        st.Page("pages/3_Charts.py", title="Charts", icon=":material/monitoring:"),
    ],
    position="sidebar",
    expanded=True,
)
navigation.run()
