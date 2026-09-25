"""Smoke test del backend: verifica el flujo completo (CRUD + agente + confirmación).

Uso:  .venv/bin/python -m scripts.smoke
"""
from __future__ import annotations

import sys
import time
import urllib.request
import json

BASE = "http://127.0.0.1:8000"


def req(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def wait_server(retries=30):
    for _ in range(retries):
        try:
            req("GET", "/api/config")
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("El servidor no respondió a tiempo")


def check(name: str, cond: bool):
    print(("  ✓ " if cond else "  ✗ ") + name)
    if not cond:
        sys.exit(1)


def main():
    print("Esperando el servidor…")
    wait_server()

    print("\n[config]")
    cfg = req("GET", "/api/config")
    check(f"config expone currency={cfg['currency']}, provider={cfg['provider']}", True)

    print("\n[categorías]")
    cats = req("GET", "/api/categories")
    names = {c["name"] for c in cats}
    check("existen categorías por defecto", {"Motos", "Comida"} <= names)

    print("\n[transacciones]")
    t = req("POST", "/api/transactions", {
        "type": "expense", "amount": 12345.67, "category": "Motos", "description": "smoke test"})
    check(f"crea transacción #{t['id']} → {t['amount_cents']} centavos", t["amount_cents"] == 1234567)
    t2 = req("POST", "/api/transactions", {"type": "income", "amount": 50000, "category": "Sueldo"})
    check(f"crea ingreso #{t2['id']}", t2["type"] == "income")

    s = req("GET", "/api/summary")
    check(f"balance > 0 (ingresos {s['total_income']} > gastos {s['total_expense']})",
          s["balance"] > 0)

    print("\n[agente — modo demo]")
    a1 = req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": "¿cuál es mi balance?"}]})
    check("respuesta de balance", a1["reply"] and "Balance" in a1["reply"])
    check("sin acción pendiente", a1["pending_action"] is None)

    print("\n[agente — acción sensible → confirmación]")
    a2 = req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": "eliminá la transacción"}]})
    check("devuelve pending_action", a2["pending_action"] is not None)
    check("pending es eliminar_transaccion", a2["pending_action"]["tool"] == "eliminar_transaccion")

    print("\n[agente — confirmación de la acción]")
    a3 = req("POST", "/api/agent/confirm", {
        "messages": [{"role": "user", "content": "eliminá la transacción"}],
        "pending_action": a2["pending_action"],
    })
    check("confirmación ejecuta y responde", a3["reply"] is not None and "eliminada" in a3["reply"])

    print("\n[agente — registro grande también pide confirmación]")
    a4 = req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": "registrá un gasto de 75.000 en Motos"}]})
    check("pending_action = registrar_transaccion", a4["pending_action"]
          and a4["pending_action"]["tool"] == "registrar_transaccion")

    print("\n[limpieza]")
    req("DELETE", f"/api/transactions/{t['id']}")
    req("DELETE", f"/api/transactions/{t2['id']}")
    check("datos de smoke eliminados", True)

    print("\n✅ Smoke test completo.")


if __name__ == "__main__":
    main()