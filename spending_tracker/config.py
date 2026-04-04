import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LLMSettings:
    provider: str | None
    model: str | None
    temperature: float

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self.model)


@dataclass(frozen=True)
class AppSettings:
    database_path: Path
    llm: LLMSettings


def _load_llm_settings() -> LLMSettings:
    provider = os.getenv("LLM_PROVIDER", "openai")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    return LLMSettings(provider=provider, model=model, temperature=temperature)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    default_db_path = _repo_root() / "spending_tracker.db"
    database_path = Path(os.getenv("SPENDING_TRACKER_DB_PATH", str(default_db_path))).expanduser()
    return AppSettings(
        database_path=database_path,
        llm=_load_llm_settings(),
    )


def get_llm_settings() -> LLMSettings:
    return get_settings().llm
