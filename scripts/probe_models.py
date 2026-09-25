"""
Descubre qué modelos de tu cuenta NVIDIA responden y cuáles
soportan tool-calling (lo que necesita el agente).

Uso:  .venv/bin/python -m scripts.probe_models
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import get_settings

URL = "https://integrate.api.nvidia.com/v1/chat/completions"

CANDIDATES = [
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/llama-3.1-nemotron-51b-instruct",
    "nvidia/nemotron-4-340b-instruct",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-nano-3-30b-a3b",
    "moonshotai/kimi-k2.6",
    "moonshotai/kimi-k3",
    "mistralai/mistral-large-2-instruct",
    "z-ai/glm-5.3",
    "openai/gpt-oss-20b",
    "qwen/qwen3-coder-480b-a35b-instruct",
    "google/gemma-4-31b-it",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calcular_balance",
            "description": "Calcula el balance (ingresos - gastos).",
            "parameters": {
                "type": "object",
                "properties": {"mes": {"type": "string", "description": "Mes en formato YYYY-MM"}},
                "required": ["mes"],
                "additionalProperties": False,
            },
        },
    }
]


def call(key: str, model: str, with_tools: bool) -> tuple[int, str, bool]:
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Usás la herramienta calcular_balance para responder."},
            {"role": "user", "content": "¿Cuál es mi balance de septiembre?"},
        ],
        "max_tokens": 64,
    }
    if with_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode())
        msg = body["choices"][0]["message"]
        has_tool = bool(msg.get("tool_calls"))
        text = (msg.get("content") or "").strip()
        return 200, (text[:80] or ("[tool_call]" if has_tool else "")), has_tool
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")[:120], False
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"[:120], False


def main() -> None:
    key = get_settings().openai_api_key
    if not key:
        print("Falta OPENAI_API_KEY")
        return

    print("Sondeo de modelos (texto + tool-calling):\n")
    working: list[tuple[str, bool]] = []
    for model in CANDIDATES:
        status, detail, has_tool = call(key, model, with_tools=True)
        if status == 200:
            icon = "✓ TOOLS" if has_tool else "✓ texto"
            print(f"{icon:8} {model}")
            print(f"         {detail}")
            working.append((model, has_tool))
        else:
            reason = "retirado (EOL)" if status == 410 else ("no disponible" if status == 404 else "error")
            print(f"✗ {status:<6}  {model}  ({reason})")

    print("\n" + "=" * 60)
    tool_models = [m for m, t in working if t]
    if tool_models:
        print("Modelos que SOPORTAN tool-calling (recomendados para el agente):")
        for m in tool_models:
            print(f"  • {m}")
    else:
        print("Ningún modelo de la lista respondió con tool-calling.")


if __name__ == "__main__":
    main()