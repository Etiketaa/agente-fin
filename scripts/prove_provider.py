"""
Sonda de verificación: comprueba que tu proveedor configurado
(OpenAI / NVIDIA / compatible) puede hacer tool-calling.

Uso:  .venv/bin/python -m scripts.prove_provider

Verifica 3 cosas:
  1. Que hay credenciales configuradas.
  2. Que el modelo responde texto.
  3. Que el modelo puede ELEGIR una herramienta cuando tiene que
     (esto es lo que hace que funcione el agente).
"""
from __future__ import annotations

import json
import sys

from app.agent.provider import get_provider
from app.config import get_settings


def main() -> None:
    settings = get_settings()

    print("=== Configuración detectada ===")
    print(f"  proveedor : {settings.llm_provider}")
    print(f"  modelo    : {settings.openai_model}")
    print(f"  base_url  : {settings.openai_base_url}")
    print(f"  api key   : {'configurada ✓' if settings.openai_api_key else 'FALTA ✗'}")

    if settings.llm_provider == "mock":
        print("\n⚠️  Estás en MODO DEMO (sin key). Configurá OPENAI_API_KEY en .env para probar el modelo real.")
        sys.exit(0)

    provider = get_provider()

    print("\n=== Prueba 1: respuesta de texto ===")
    try:
        text, tool_calls = provider.chat(
            [
                {"role": "system", "content": "Respondé en español, con una sola palabra."},
                {"role": "user", "content": "¿De qué color es el cielo en un día claro?"},
            ],
            tools=None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ Error llamando al modelo: {type(exc).__name__}: {exc}")
        sys.exit(1)

    if text:
        print(f'  ✓ "{text.strip()[:120]}"')
    else:
        print("  ✗ El modelo no devolvió texto.")

    print("\n=== Prueba 2: tool-calling (lo crítico para el agente) ===")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calcular_balance",
                "description": "Calcula el balance (ingresos - gastos) en un período.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "desde": {"type": "string", "description": "Fecha inicial YYYY-MM-DD"}
                    },
                    "additionalProperties": False,
                },
            },
        }
    ]
    try:
        text2, tool_calls2 = provider.chat(
            [
                {"role": "system", "content": "Usás la herramienta calcular_balance para responder preguntas de balance."},
                {"role": "user", "content": "¿Cuál es mi balance de septiembre?"},
            ],
            tools=tools,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ Error en tool-calling: {type(exc).__name__}: {exc}")
        sys.exit(1)

    if tool_calls2:
        tc = tool_calls2[0]
        print(f"  ✓ El modelo eligió la herramienta: {tc.name}")
        print(f"    argumentos: {json.dumps(tc.arguments, ensure_ascii=False)}")
        print("\n✅ El agente puede usar herramientas con este modelo. Podés usar la app.")
    else:
        print(f"  ✗ El modelo NO llamó a la herramienta (respondió texto: {text2!r})")
        print("    → Ese modelo probablemente no soporta function calling.")
        print("    → Probá con: nvidia/nemotron-3-super-120b-a12b")
        sys.exit(1)


if __name__ == "__main__":
    main()