from __future__ import annotations

from typing import Any

from spending_tracker.config import get_llm_settings


def build_llm() -> Any | None:
    settings = get_llm_settings()
    if not settings.enabled:
        return None

    provider = settings.provider.lower()
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.model, temperature=settings.temperature, max_retries=1)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.model, temperature=settings.temperature, max_retries=1)

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=settings.model, temperature=settings.temperature)
    return None
