"""Configuración de la aplicación, leída desde variables de entorno (.env)."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def db_fingerprint(database_url: str) -> str:
    """Huella corta de la base, sin credenciales: solo motor, host y nombre.

    La publica `/health` para que un test pueda confirmar que el servidor al que
    le está hablando usa la MISMA base que él, antes de ir a modificarla. Sin esto,
    correr el smoke contra un servidor local mientras `DATABASE_URL` apunta a la
    base real terminaría escribiendo datos de prueba en producción.

    El hash es sobre la parte no secreta de la URL: la contraseña nunca entra en la
    semilla, así que la huella no sirve para adivinarla.
    """
    partes = urlsplit(database_url)
    semilla = f"{partes.scheme}|{partes.hostname}|{(partes.path or '').strip('/')}"
    return hashlib.sha256(semilla.encode()).hexdigest()[:12]


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
    budget_alert_pct: float  # fracción del presupuesto que dispara la alerta (0.8 = 80%)
    session_ttl_days: int  # cuánto vive una sesión antes de exigir login de nuevo
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
        budget_alert_pct=float(os.getenv("BUDGET_ALERT_PCT", "0.8")),
        session_ttl_days=int(os.getenv("SESSION_TTL_DAYS", "30")),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
