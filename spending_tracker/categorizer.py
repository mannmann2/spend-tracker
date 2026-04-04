import json
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from spending_tracker.db import get_mapping, upsert_mapping
from spending_tracker.llm import build_llm
from spending_tracker.parser import merchant_key


DEFAULT_CATEGORIES = [
    "Groceries",
    "Dining",
    "Transport",
    "Utilities",
    "Rent",
    "Mortgage",
    "Healthcare",
    "Fitness",
    "Entertainment",
    "Shopping",
    "Travel",
    "Insurance",
    "Income",
    "Savings",
    "Cash Withdrawal",
    "Transfers",
    "Subscriptions",
    "Education",
    "Other",
]


@dataclass
class CategorizationResult:
    category: str | None
    source: str
    confidence: float
    error: str | None = None


def _extract_json_payload(content: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return content.strip()


def _normalize_response_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def _parse_category_response(content) -> tuple[str, float]:
    normalized = _normalize_response_content(content)
    payload_text = _extract_json_payload(normalized)

    try:
        payload = json.loads(payload_text)
        if isinstance(payload, dict):
            category = str(payload.get("category", "")).strip()
            confidence = float(payload.get("confidence", 0.5))
            if category:
                return category, confidence
    except Exception:
        pass

    category_match = re.search(r'"?category"?\s*[:=]\s*"?(?P<category>[A-Za-z &-]+)"?', normalized, re.IGNORECASE)
    confidence_match = re.search(r'"?confidence"?\s*[:=]\s*"?(?P<confidence>\d*\.?\d+)"?', normalized, re.IGNORECASE)
    if category_match:
        category = category_match.group("category").strip()
        confidence = float(confidence_match.group("confidence")) if confidence_match else 0.5
        return category, confidence

    stripped = normalized.strip()
    if stripped in DEFAULT_CATEGORIES:
        return stripped, 0.5

    raise ValueError(f"Could not parse category response: {normalized[:200]}")


def categorize_transaction(description: str, amount: float, direction: str) -> CategorizationResult:
    m_key = merchant_key(description)
    mapped = get_mapping(m_key)
    if mapped:
        return CategorizationResult(category=mapped, source="mapping", confidence=1.0)

    llm = build_llm()
    if llm is None:
        return CategorizationResult(
            category=None,
            source="llm_error",
            confidence=0.0,
            error="No LLM provider is available. Check provider/model/API key configuration.",
        )

    system = SystemMessage(
        content=(
            "You categorize bank transactions. "
            "Choose the single best category from this list: "
            f"{', '.join(DEFAULT_CATEGORIES)}. "
            "Return JSON with keys category and confidence."
        )
    )
    human = HumanMessage(
        content=(
            f"Description: {description}\n"
            f"Amount: {amount}\n"
            f"Direction: {direction}\n"
            "If uncertain, use Other."
        )
    )

    try:
        response = llm.invoke([system, human])
        category, confidence = _parse_category_response(response.content)
        if category not in DEFAULT_CATEGORIES:
            category = "Other"
        upsert_mapping(m_key, category, transaction_source="llm_mapping")
        return CategorizationResult(
            category=category,
            source="llm",
            confidence=max(0.0, min(confidence, 1.0)),
        )
    except Exception as exc:
        return CategorizationResult(
            category=None,
            source="llm_error",
            confidence=0.0,
            error=str(exc),
        )
