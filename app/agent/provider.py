"""
Capa de proveedor de LLM — el punto de la arquitectura que hace
intercambiable el modelo (OpenAI, Anthropic, Google, local, etc.).

Todo el resto de la app depende de `get_provider().chat(...)`.
Para agregar un proveedor nuevo: implementá la misma interfaz y
registralo en `get_provider`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ToolCall:
    name: str
    arguments: dict


class ProviderError(RuntimeError):
    """Falla del proveedor de LLM (red, timeout, 5xx, auth, rate limit).

    Se traduce a un mensaje entendible en la capa de API, para que un problema
    externo se vea como "el proveedor no respondió" y no como un error 500
    propio con un traceback. El detalle técnico queda encadenado en `__cause__`
    para el log del servidor.
    """


class MockProvider:
    """Modo demo: respuestas simuladas por reglas, sin API key ni costo."""

    model: str = "mock"

    def __init__(self, currency: str = "ARS"):
        self.currency = currency

    def chat(self, messages: list[dict], tools: list[dict] | None):
        # Si ya se ejecutó una herramienta, responder con su resultado
        # (en vez de volver a dispararla en loop).
        if messages and messages[-1].get("role") == "tool":
            return f"Acá está la información que pediste:\n{messages[-1]['content']}", None

        user_msgs = [m for m in messages if m.get("role") == "user"]
        text = user_msgs[-1]["content"].lower() if user_msgs else ""

        if any(k in text for k in ("balance", "saldo")):
            return None, [ToolCall("calcular_balance", {})]
        if any(k in text for k in ("objetivo", "meta", "ahorro", "ahorrar")):
            return None, [ToolCall("listar_objetivos", {})]
        if "presupuesto" in text or "presupuestos" in text:
            return None, [ToolCall("listar_presupuestos", {})]
        if "resumen" in text or "categor" in text:
            return None, [ToolCall("resumen_por_categoria", {})]
        if any(k in text for k in ("transacciones", "movimientos", "list")):
            return None, [ToolCall("listar_transacciones", {"limite": 20})]
        if any(k in text for k in ("elimin", "borr", "saca")):
            m = re.search(r"\b(\d+)\b", text)
            target_id = int(m.group(1)) if m else 1
            return None, [ToolCall("eliminar_transaccion", {"id": target_id})]
        if any(k in text for k in ("registr", "agreg", "anota", "gasto", "ingreso")):
            return None, [
                ToolCall(
                    "registrar_transaccion",
                    {"tipo": "expense", "monto": 75000, "categoria": "Motos",
                     "descripcion": "Registro de prueba (modo demo)"},
                )
            ]

        return (
            "Modo demo activo (respondo sin API key). Podés pedirme tu balance, "
            "un resumen por categoría, tus transacciones, tus objetivos de ahorro, "
            "cómo venís con los presupuestos, registrar un gasto o eliminar una "
            "transacción. Para respuestas reales configurá OPENAI_API_KEY (ver README).",
            None,
        )


class OpenAIProvider:
    """
    Proveedor OpenAI — y cualquier API compatible
    (OpenAI, OpenRouter, Ollama, LM Studio, vLLM, etc. vía OPENAI_BASE_URL).
    """

    def __init__(self, api_key: str | None, base_url: str | None, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def chat(self, messages: list[dict], tools: list[dict] | None):
        from openai import APIError

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or None,
                temperature=0.2,
            )
        except APIError as exc:
            raise ProviderError(_friendly_provider_error(exc)) from exc
        msg = resp.choices[0].message
        text = msg.content
        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(ToolCall(tc.function.name, args))
        return text, tool_calls


def _friendly_provider_error(exc: Exception) -> str:
    """Traduce una excepción del SDK a un mensaje que el usuario pueda usar."""
    from openai import (
        APIConnectionError,
        APIStatusError,
        AuthenticationError,
        APITimeoutError,
        RateLimitError,
    )

    if isinstance(exc, AuthenticationError):
        return ("Credenciales del proveedor inválidas. Revisá OPENAI_API_KEY en .env.")
    if isinstance(exc, RateLimitError):
        return ("El proveedor está limitando las requests. Esperá unos segundos y reintentá.")
    if isinstance(exc, APITimeoutError):
        return ("El proveedor tardó demasiado en responder. Reintentá en un momento.")
    if isinstance(exc, APIConnectionError):
        return f"No se pudo conectar con el proveedor: {exc.__class__.__name__}."
    if isinstance(exc, APIStatusError):
        return (f"El proveedor respondió con un error {exc.status_code}. "
                "Suele ser un problema momentáneo del servicio: reintentá.")
    return f"Error inesperado del proveedor: {exc}"


def get_provider():
    from ..config import get_settings

    s = get_settings()
    if s.llm_provider == "openai":
        return OpenAIProvider(s.openai_api_key, s.openai_base_url, s.openai_model)
    return MockProvider(s.currency)