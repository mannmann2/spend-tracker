import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO

import pdfplumber
from langchain_core.messages import HumanMessage, SystemMessage

from spending_tracker.llm import build_llm

logger = logging.getLogger(__name__)


TRANSACTION_EXTRACTION_SCHEMA = {
    "title": "statement_transactions",
    "description": "Transactions extracted from raw bank statement text.",
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "txn_date": {"type": "string"},
                    "description": {"type": "string"},
                    "amount": {"type": ["string", "number"]},
                    "direction": {"type": "string", "enum": ["debit", "credit"]},
                    "raw_line": {"type": "string"},
                },
                "required": ["txn_date", "description", "amount", "direction", "raw_line"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["transactions"],
    "additionalProperties": False,
}

TRANSACTION_EXTRACTION_SYSTEM_PROMPT = """
Extract bank statement transactions from raw statement text.

Return only transactions that are explicitly present in the statement's transaction list.
Ignore headers, contact details, addresses, balances, credit limits, payment due summaries,
opening balance, closing balance, "money in/out" summaries, interest summaries, and page furniture.

Important rules:
- Output strict JSON matching the provided schema.
- Use ISO dates in YYYY-MM-DD format.
- Preserve the merchant/transaction description from the statement text.
- A single transaction can span multiple lines. Combine the lines that belong to one transaction.
- Some statements include a running balance after the transaction amount. Use the transaction amount, not the running balance.
- For rows like `-£2.00 £22.84` or `+£100.00 £108.34`, the first money value is the transaction amount and the last money value is the balance.
- Exclude rows for opening balance and closing balance even if they appear inside the transaction table.
- For card statements, rows labelled Purchase, Card Purchase, Cash Transaction, Fee, or similar are debits.
- Rows labelled Payment, Refund, Credit, Reversal, or similar are credits.
- For current account statements, incoming transfers such as `From Chase Saver` or `From Payments` are credits, and outgoing transfers/payments such as `To Credit Card` are debits.
- Amount must be the transaction amount only, not the running balance.
- raw_line should contain the source statement text for that transaction, with wrapped lines combined.
- Do not invent missing transactions.
""".strip()


@dataclass
class ParsedTransaction:
    txn_date: str
    description: str
    amount: float
    direction: str
    raw_line: str


@dataclass
class ParseDiagnostics:
    text_preview: str
    line_count: int
    parser_used: str
    warnings: list[str] = field(default_factory=list)
    llm_attempted: bool = False
    llm_succeeded: bool = False


def hash_bytes(file_bytes: bytes) -> str:
    digest = hashlib.sha256(file_bytes).hexdigest()
    logger.debug("Computed PDF hash", extra={"file_size": len(file_bytes), "hash": digest})
    return digest


def get_pdf_page_count(file_bytes: bytes) -> int:
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)
    logger.info("Counted PDF pages", extra={"page_count": page_count})
    return page_count


def extract_text_from_pdf(file_bytes: bytes, page_numbers: list[int] | None = None) -> str:
    pages = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        selected_pages = page_numbers if page_numbers is not None else list(range(len(pdf.pages)))
        logger.info(
            "Starting PDF text extraction",
            extra={"page_count": len(pdf.pages), "selected_pages": selected_pages},
        )
        for page_index in selected_pages:
            if page_index < 0 or page_index >= len(pdf.pages):
                logger.warning(
                    "Skipping out-of-range page during extraction", extra={"page_index": page_index}
                )
                continue
            page_text = pdf.pages[page_index].extract_text() or ""
            logger.debug(
                "Extracted page text",
                extra={"page_index": page_index, "text_length": len(page_text)},
            )
            pages.append(page_text)
    combined = "\n".join(pages)
    logger.info(
        "Completed PDF text extraction",
        extra={"selected_page_count": len(pages), "text_length": len(combined)},
    )
    return combined


def merchant_key(description: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char == " " else " " for char in description.lower()
    )
    for token in ("card", "debit", "purchase", "pos", "payment", "ref", "visa", "mastercard"):
        cleaned = cleaned.replace(token, " ")
    cleaned = " ".join(cleaned.split())
    return cleaned[:120] or "unknown"


def _validate_iso_date(raw_date: str) -> str | None:
    try:
        return date.fromisoformat(raw_date.strip()).isoformat()
    except ValueError:
        return None


def _normalize_text(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        normalized = " ".join(raw_line.replace("\u00a0", " ").split())
        if normalized:
            lines.append(normalized)
    logger.debug("Normalized extracted text", extra={"line_count": len(lines)})
    return lines


def _clean_amount(raw_amount: str) -> tuple[float | None, str]:
    token = raw_amount.strip().lower()
    direction = "credit" if token.startswith("+") or token.endswith("cr") else "debit"
    negative = token.startswith("-") or token.startswith("(")
    token = (
        token.replace("cr", "").replace("dr", "").replace("$", "").replace("£", "").replace("€", "")
    )
    token = token.replace("+", "")
    token = token.replace(",", "").replace("(", "").replace(")", "").strip()
    try:
        amount = abs(float(token))
    except ValueError:
        return None, "debit"
    if negative:
        direction = "debit"
    return amount, direction


def _dedupe_transactions(transactions: list[ParsedTransaction]) -> list[ParsedTransaction]:
    seen: set[tuple[str, str, float]] = set()
    deduped: list[ParsedTransaction] = []
    duplicate_count = 0
    for txn in transactions:
        key = (txn.txn_date, txn.description.lower(), txn.amount)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        deduped.append(txn)
    logger.info(
        "Deduplicated transactions",
        extra={
            "input_count": len(transactions),
            "output_count": len(deduped),
            "duplicates_removed": duplicate_count,
        },
    )
    return deduped


def _chunk_text_for_llm(text: str, max_chars: int = 14000) -> list[str]:
    lines = _normalize_text(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
            continue
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    logger.info(
        "Chunked statement text for LLM", extra={"chunk_count": len(chunks), "max_chars": max_chars}
    )
    return chunks


def _extract_message_text(payload: object) -> str:
    if isinstance(payload, str):
        return payload

    content = getattr(payload, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return ""


def _coerce_payload_to_items(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        items = payload.get("transactions")
        return items if isinstance(items, list) else []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    raw_text = _extract_message_text(payload).strip()
    if not raw_text:
        return []

    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    return _coerce_payload_to_items(decoded)


def _build_fallback_messages(chunk: str) -> list[object]:
    return [
        SystemMessage(content=TRANSACTION_EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                "Extract the transactions from the bank statement text below.\n"
                "Return a strict JSON object with a single key `transactions`.\n"
                "Statement text:\n"
                f"{chunk}"
            )
        ),
    ]


def _parse_transactions_from_items(items: list[dict]) -> list[ParsedTransaction]:
    transactions: list[ParsedTransaction] = []
    skipped_items = 0
    for item in items:
        txn_date = _validate_iso_date(str(item.get("txn_date", "")))
        description = str(item.get("description", "")).strip()
        raw_line = str(item.get("raw_line", description)).strip()
        amount_raw = str(item.get("amount", "")).strip()
        direction = str(item.get("direction", "debit")).strip().lower()
        amount, fallback_direction = _clean_amount(amount_raw)
        if amount is None or not txn_date or len(description) < 3:
            skipped_items += 1
            continue
        if direction not in {"debit", "credit"}:
            direction = fallback_direction
        transactions.append(
            ParsedTransaction(
                txn_date=txn_date,
                description=description,
                amount=amount,
                direction=direction,
                raw_line=raw_line or description,
            )
        )
    logger.info(
        "Converted LLM payload items into transactions",
        extra={
            "item_count": len(items),
            "transaction_count": len(transactions),
            "skipped_items": skipped_items,
        },
    )
    return transactions


def llm_parse_transactions(text: str) -> list[ParsedTransaction]:
    llm = build_llm()
    if llm is None:
        logger.warning("No LLM configured for transaction parsing")
        return []

    logger.info("Starting LLM transaction parsing")
    try:
        structured_llm = llm.with_structured_output(TRANSACTION_EXTRACTION_SCHEMA)
        logger.debug("Structured output configured for transaction extraction")
    except Exception:
        structured_llm = None
        logger.warning(
            "Structured output unavailable; transaction parsing will use fallback prompts"
        )

    transactions: list[ParsedTransaction] = []
    chunks = _chunk_text_for_llm(text)
    for index, chunk in enumerate(chunks, start=1):
        items: list[dict] = []

        if structured_llm is not None:
            logger.info(
                "Submitting chunk to structured LLM parser",
                extra={
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "chunk_length": len(chunk),
                },
            )
            try:
                payload = structured_llm.invoke(
                    [
                        SystemMessage(content=TRANSACTION_EXTRACTION_SYSTEM_PROMPT),
                        HumanMessage(content=chunk),
                    ]
                )
                logger.debug("Received structured LLM payload", extra={"chunk_index": index})
                items = _coerce_payload_to_items(payload)
                logger.info(
                    "Coerced structured LLM payload",
                    extra={"chunk_index": index, "item_count": len(items)},
                )
            except Exception:
                items = []
                logger.exception("Structured LLM parsing failed", extra={"chunk_index": index})

        if not items:
            logger.warning(
                "Structured LLM returned no items; falling back to plain prompt",
                extra={"chunk_index": index},
            )
            try:
                payload = llm.invoke(_build_fallback_messages(chunk))
                items = _coerce_payload_to_items(payload)
                logger.info(
                    "Coerced fallback LLM payload",
                    extra={"chunk_index": index, "item_count": len(items)},
                )
            except Exception:
                items = []
                logger.exception("Fallback LLM parsing failed", extra={"chunk_index": index})

        transactions.extend(_parse_transactions_from_items(items))
    logger.info("Completed LLM transaction parsing", extra={"transaction_count": len(transactions)})
    return transactions


def parse_transactions(text: str) -> tuple[list[ParsedTransaction], ParseDiagnostics]:
    lines = _normalize_text(text)
    warnings: list[str] = []
    logger.info(
        "Starting parse_transactions", extra={"text_length": len(text), "line_count": len(lines)}
    )

    if not lines:
        warnings.append(
            "No text was extracted from the PDF. This may be a scanned statement that needs OCR."
        )
        logger.warning("No normalized lines found during transaction parsing")
        diagnostics = ParseDiagnostics(
            text_preview="",
            line_count=0,
            parser_used="none",
            warnings=warnings,
            llm_attempted=False,
            llm_succeeded=False,
        )
        return [], diagnostics

    transactions = llm_parse_transactions(text)
    llm_succeeded = bool(transactions)
    if not llm_succeeded:
        warnings.append("LLM extraction did not return any valid transactions.")
        logger.warning("LLM extraction returned no valid transactions")

    diagnostics = ParseDiagnostics(
        text_preview="\n".join(lines),
        line_count=len(lines),
        parser_used="llm",
        warnings=warnings,
        llm_attempted=True,
        llm_succeeded=llm_succeeded,
    )
    logger.info(
        "Completed parse_transactions",
        extra={
            "transaction_count": len(transactions),
            "warning_count": len(warnings),
            "llm_succeeded": llm_succeeded,
        },
    )
    return transactions, diagnostics
