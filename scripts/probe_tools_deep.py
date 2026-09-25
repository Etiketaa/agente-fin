"""
Segunda pasada: reintenta los modelos que respondieron con texto de
razonamiento usando más tokens, para ver si realmente pueden emitir
tool_calls (los modelos de razonamiento consumen tokens pensando).

Uso:  .venv/bin/python -m scripts.probe_tools_deep
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from app.config import get_settings

URL = "https://integrate.api.nvidia.com/v1/chat/completions"

MODELS = [
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "z-ai/glm-5.3",
    "moonshotai/kimi-k3",
    "openai/gpt-oss-20b",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "registrar_transaccion",
            "description": "Registra un ingreso o gasto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["income", "expense"]},
                    "monto": {"type": "number"},
                    "categoria": {"type": "string"},
                },
                "required": ["tipo", "monto", "categoria"],
                "additionalProperties": False,
            },
        },
    }
]


def test(key: str, model: str) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Registrás movimientos con la herramienta. No inventes datos."},
            {"role": "user", "content": "Registrá un gasto de 75.000 pesos en la categoría Motos."},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 2048,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "elapsed": time.time() - t0}
    except Exception as exc:  # noqa: BLE001
        return {"status": -1, "elapsed": time.time() - t0, "error": str(exc)[:80]}

    choice = body["choices"][0]
    msg = choice["message"]
    tool_calls = msg.get("tool_calls") or []
    return {
        "status": 200,
        "elapsed": time.time() - t0,
        "finish": choice.get("finish_reason"),
        "tool_calls": tool_calls,
        "content": (msg.get("content") or "")[:100],
        "reasoning": bool(msg.get("reasoning_content")),
    }


def main() -> None:
    key = get_settings().openai_api_key
    print(f"{'model':45} {'tool?':6} {'finish':12} {'seg':>6}")
    print("-" * 78)
    for model in MODELS:
        r = test(key, model)
        if r["status"] != 200:
            print(f"{model:45} HTTP {r['status']:<4}")
            continue
        has = "✓ SÍ" if r["tool_calls"] else "✗ no"
        args = ""
        if r["tool_calls"]:
            fn = r["tool_calls"][0]["function"]
            args = f"  → {fn['name']}({fn['arguments'][:60]})"
        print(f"{model:45} {has:6} {str(r['finish']):12} {r['elapsed']:6.1f}{args}")


if __name__ == "__main__":
    main()