from dataclasses import dataclass

from spending_tracker.categorizer import categorize_transaction
from spending_tracker.db import (
    get_or_create_account,
    get_uncategorized,
    insert_statement,
    save_transactions,
    statement_exists,
    update_transaction_category,
)
from spending_tracker.parser import (
    ParseDiagnostics,
    extract_text_from_pdf,
    get_pdf_page_count,
    hash_bytes,
    merchant_key,
    parse_transactions,
)


@dataclass
class IngestResult:
    parsed_count: int
    inserted_count: int
    message: str
    diagnostics: ParseDiagnostics


@dataclass
class RecategorizeResult:
    updated_count: int
    remaining_count: int
    error_count: int
    sample_error: str | None = None


def _statement_page_numbers(account_name: str, file_bytes: bytes) -> list[int] | None:
    normalized = account_name.strip().lower()
    if normalized not in {"amex", "chase credit"}:
        return None

    total_pages = get_pdf_page_count(file_bytes)
    if total_pages <= 4:
        return list(range(total_pages))
    return list(range(1, total_pages - 3))


def ingest_statement(uploaded_file, account_name: str) -> IngestResult:
    file_bytes = uploaded_file.getvalue()
    file_hash = hash_bytes(file_bytes)
    if statement_exists(file_hash):
        return IngestResult(
            parsed_count=0,
            inserted_count=0,
            message="This statement has already been uploaded.",
            diagnostics=ParseDiagnostics(
                text_preview="",
                line_count=0,
                parser_used="duplicate",
                warnings=[],
                llm_attempted=False,
                llm_succeeded=False,
            ),
        )

    account_id = get_or_create_account(account_name)
    statement_id = insert_statement(account_id, uploaded_file.name, file_hash)
    page_numbers = _statement_page_numbers(account_name, file_bytes)
    text = extract_text_from_pdf(file_bytes, page_numbers=page_numbers)
    parsed, diagnostics = parse_transactions(text)

    rows: list[dict] = []
    for txn in parsed:
        result = categorize_transaction(
            description=txn.description,
            amount=txn.amount,
            direction=txn.direction,
        )
        rows.append(
            {
                "statement_id": statement_id,
                "account_id": account_id,
                "txn_date": txn.txn_date,
                "description": txn.description,
                "merchant_key": merchant_key(txn.description),
                "amount": txn.amount,
                "direction": txn.direction,
                "category": result.category,
                "source": result.source,
                "raw_line": txn.raw_line,
                "confidence": result.confidence,
            }
        )

    inserted = save_transactions(rows)
    message = f"Processed {len(parsed)} candidate transactions using {diagnostics.parser_used} parsing."
    return IngestResult(
        parsed_count=len(parsed),
        inserted_count=inserted,
        message=message,
        diagnostics=diagnostics,
    )


def recategorize_uncategorized_transactions() -> RecategorizeResult:
    uncategorized = get_uncategorized()
    updated_count = 0
    error_count = 0
    sample_error: str | None = None

    for row in uncategorized.itertuples(index=False):
        result = categorize_transaction(
            description=row.description,
            amount=row.amount,
            direction=row.direction,
        )
        if result.category:
            update_transaction_category(
                transaction_id=int(row.id),
                category=result.category,
                source=result.source,
                confidence=result.confidence,
            )
            updated_count += 1
        else:
            update_transaction_category(
                transaction_id=int(row.id),
                category=None,
                source=result.source,
                confidence=result.confidence,
            )
            error_count += 1
            if sample_error is None:
                sample_error = result.error

    remaining_count = len(get_uncategorized())
    return RecategorizeResult(
        updated_count=updated_count,
        remaining_count=remaining_count,
        error_count=error_count,
        sample_error=sample_error,
    )
