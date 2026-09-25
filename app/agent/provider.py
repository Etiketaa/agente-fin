"""
Capa de proveedor de LLM — el punto de la arquitectura que hace
intercambiable el modelo (OpenAI, Anthropic, Google, local, etc.).

Todo el resto de la app depende de `get_provider().chat(...)`.
Para agregar un proveedor nuevo: implementá la misma interfaz y
registralo en `get_provider`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ToolCall:
    name: str
    arguments: dict


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
        if "resumen" in text or "categor" in text:
            return None, [ToolCall("resumen_por_categoria", {})]
        if any(k in text for k in ("transacciones", "movimientos", "list")):
            return None, [ToolCall("listar_transacciones", {"limite": 20})]
        if any(k in text for k in ("elimin", "borr", "saca")):
            return None, [ToolCall("eliminar_transaccion", {"id": 1})]
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
            "un resumen por categoría, tus transacciones, registrar un gasto o eliminar "
            "una transacción. Para respuestas reales configurá OPENAI_API_KEY (ver README).",
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
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
            temperature=0.2,
        )
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


def get_provider():
    from ..config import get_settings

    s = get_settings()
    if s.llm_provider == "openai":
        return OpenAIProvider(s.openai_api_key, s.openai_base_url, s.openai_model)
    return MockProvider(s.currency)