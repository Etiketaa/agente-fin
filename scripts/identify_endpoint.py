"""
Identifica a qué endpoint corresponde tu API key probando los
candidatos de NVIDIA. No imprime la key.

Uso:  .venv/bin/python -m scripts.identify_endpoint
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import get_settings

MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"

CANDIDATES = [
    ("API catalog (chat)", "https://integrate.api.nvidia.com/v1/chat/completions", MODEL),
    ("API catalog (legacy complete)", "https://integrate.api.nvidia.com/v1/completions", MODEL),
    ("build.nvidia.com", "https://build.nvidia.com/v1/chat/completions", MODEL),
    ("ai.api.nvidia.com", "https://ai.api.nvidia.com/v1/chat/completions", MODEL),
    ("nim proxy (api.nim.ai)", "https://api.nim.ai/v1/chat/completions", MODEL),
    ("NGC org/llama-3.1-nemotron", "https://integrate.api.nvidia.com/v1/chat/completions",
     "meta/llama-3.1-70b-instruct"),
]


def probe(label: str, url: str, model: str, key: str) -> tuple[str, str]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode()
        return "200 OK", body[:160]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        return f"HTTP {exc.code}", detail
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, str(exc)[:160]


def main() -> None:
    s = get_settings()
    if not s.openai_api_key:
        print("Falta OPENAI_API_KEY en .env")
        return
    key = s.openai_api_key

    print("Probando endpoints con tu key (no se imprime la key):\n")
    for label, url, model in CANDIDATES:
        status, detail = probe(label, url, model, key)
        icon = "✓" if "200" in status else "✗"
        print(f"{icon} {label:32} [{model[:38]}]  {status}")
        print(f"   {detail}\n")

    # ¿La key siquiera autentica contra el catálogo?
    req = urllib.request.Request(
        "https://integrate.api.nvidia.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"GET /v1/models autenticado: {resp.status} OK (la key es válida para el catálogo)")
    except urllib.error.HTTPError as exc:
        print(f"GET /v1/models autenticado: HTTP {exc.code} — la key NO pertenece al catálogo público")


if __name__ == "__main__":
    main()