# LLM Spending Tracker

A Streamlit app for ingesting PDF bank statements, classifying spending, correcting categories, and exploring trends with interactive charts.

## Purpose

This project is a personal finance workflow for turning PDF bank statements into structured transactions, category mappings, grouped spending views, and chart-based analysis with a lightweight local SQLite store.

## Current Limitations

- Statement ingestion depends on extractable PDF text; scanned PDFs still need OCR before parsing can work well.
- LLM-backed parsing and categorisation depend on external provider credentials when you want automated classification.
- The app is designed for local use with a single-user SQLite database rather than concurrent multi-user access.

## Features

- Drag-and-drop PDF statement uploads for multiple bank accounts
- Automatic transaction extraction and storage in SQLite
- LLM-based statement parsing through LangChain
- LLM-first transaction categorisation for new merchants, with persistent mappings for known merchants
- Merchant/category mappings learned from both LLM classification and user corrections
- Filters by date, category, account, and transaction type
- Card-based grouped spending views by month, year, category, account, and more
- Interactive Plotly visualisations for spending over time

## Project Structure

- `app.py`: Streamlit home page with overview and grouped spending cards
- `pages/`: Streamlit pages for Upload, Mappings, and Charts
- `spending_tracker/db.py`: SQLite persistence
- `spending_tracker/parser.py`: PDF statement parsing
- `spending_tracker/categorizer.py`: Mapping + LLM categorisation logic
- `spending_tracker/analytics.py`: Aggregation helpers
- `spending_tracker/services.py`: Statement ingestion workflow
- `spending_tracker/config.py`: Environment-based app and LLM configuration
- `ui/`: Shared Streamlit helpers and page renderers

## Running Locally

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -e ".[dev]"
```

3. Optionally configure LLM provider credentials:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=your_key
export LLM_MODEL=gpt-4.1-mini
```

Optional runtime configuration:

```bash
export SPENDING_TRACKER_DB_PATH=/absolute/path/to/spending_tracker.db
```

Supported `LLM_PROVIDER` values:

- `openai`
- `anthropic`
- `google`

If no provider is configured, uncategorised transactions remain for user review until you configure an LLM or map them manually.

4. Start the app:

```bash
streamlit run app.py
```

## Development

Lint the repo:

```bash
ruff check .
```

Format the repo:

```bash
ruff format .
```

## Notes

- Statement ingestion now uses an LLM-based extractor by default. The app expects the model to return ISO-formatted transaction dates, with a light validator before records are stored.
- If the PDF is scanned and contains no extractable text, OCR is still required before the LLM has anything useful to parse.
- The first successful LLM category for a new merchant is stored as that merchant's reusable mapping, and user corrections can override it later.
- The local SQLite database is ignored by git and generated on demand. By default it lives at `spending_tracker.db` in the project root unless `SPENDING_TRACKER_DB_PATH` is set.
