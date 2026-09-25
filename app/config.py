"""Configuración de la aplicación, leída desde variables de entorno (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    currency: str
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    llm_provider: str  # "mock" | "openai"
    sensitive_amount: float  # en unidades de moneda (no centavos)
    host: str
    port: int


def get_settings() -> Settings:
    api_key = os.getenv("OPENAI_API_KEY") or None
    force_mock = _bool(os.getenv("LLM_MOCK"))
    provider = "mock" if (force_mock or not api_key) else "openai"
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./finanzas.db"),
        currency=os.getenv("CURRENCY", "ARS"),
        openai_api_key=api_key,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        llm_provider=provider,
        sensitive_amount=float(os.getenv("SENSITIVE_AMOUNT", "50000")),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )