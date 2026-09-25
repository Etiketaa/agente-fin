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


def cleanup(ids: list[int]):
    for tid in ids:
        try:
            req("DELETE", f"/api/transactions/{tid}")
        except Exception:
            pass


def main():
    created_ids: list[int] = []
    try:
        _run(created_ids)
        print("\n✅ Smoke test completo.")
    finally:
        if created_ids:
            cleanup(created_ids)


def _run(created_ids: list[int]):
    print("Esperando el servidor…")
    wait_server()

    print("\n[health]")
    health = req("GET", "/health")
    check("health endpoint responde", health.get("status") == "ok")

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
    created_ids.append(t["id"])
    check(f"crea transacción #{t['id']} → {t['amount_cents']} centavos", t["amount_cents"] == 1234567)
    t2 = req("POST", "/api/transactions", {"type": "income", "amount": 50000, "category": "Sueldo"})
    created_ids.append(t2["id"])
    check(f"crea ingreso #{t2['id']}", t2["type"] == "income")

    s = req("GET", "/api/summary")
    check("resumen coherente (balance = ingresos − gastos)",
          abs(s["balance"] - (s["total_income"] - s["total_expense"])) < 0.01)
    check("hay ingresos y gastos", s["total_income"] > 0 and s["total_expense"] > 0)

    print(f"\n[agente — proveedor {cfg['provider']}]")
    a1 = req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": "¿cuál es mi balance?"}]})
    check("devuelve una respuesta de balance no vacía", bool(a1["reply"]))
    check("sin acción pendiente", a1["pending_action"] is None)

    print("\n[agente — acción sensible → confirmación]")
    tx3 = req("POST", "/api/transactions", {"type": "expense", "amount": 9999, "category": "Motos"})
    check(f"crea transacción #{tx3['id']} para el test de borrado", True)
    msg = f"eliminá la transacción {tx3['id']}"
    a2 = req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": msg}]})
    check("devuelve pending_action", a2["pending_action"] is not None)
    check("pending es eliminar_transaccion", a2["pending_action"]["tool"] == "eliminar_transaccion")
    check("pending apunta al id correcto", a2["pending_action"]["args"]["id"] == tx3["id"])

    print("\n[agente — confirmación de la acción]")
    a3 = req("POST", "/api/agent/confirm", {
        "messages": [{"role": "user", "content": msg}],
        "pending_action": a2["pending_action"],
    })
    check("confirmación ejecuta y responde", a3["reply"] is not None and "eliminada" in a3["reply"])

    print("\n[agente — registro grande también pide confirmación]")
    a4 = req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": "registrá un gasto de 75.000 en Motos"}]})
    check("pending_action = registrar_transaccion", a4["pending_action"]
          and a4["pending_action"]["tool"] == "registrar_transaccion")

    print("\n[verificación — la transacción del test quedó eliminada]")
    lista = req("GET", "/api/transactions?limite=100")
    check(f"la #{tx3['id']} no figura en la lista", all(t["id"] != tx3["id"] for t in lista))
    if tx3["id"] in created_ids:
        created_ids.remove(tx3["id"])


if __name__ == "__main__":
    main()