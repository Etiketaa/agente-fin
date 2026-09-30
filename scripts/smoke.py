"""Smoke test del backend: verifica el flujo completo (CRUD + agente + confirmación).

Uso:  .venv/bin/python -m scripts.smoke

El test crea datos contra la base real y los borra al terminar. Los IDs que
crea se van acumulando en `created` para que la limpieza sea lo más completa
posible aunque el script falle a mitad de camino.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

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


def agent_req(method: str, path: str, payload: dict, attempts: int = 3):
    """Llama al agente reintentando si el proveedor externo falla.

    La sección del agente depende de un servicio de terceros (NVIDIA, OpenAI,
    etc.) que a veces devuelve un 5xx momentáneo. Reintentar distingue "el
    proveedor se cayó un segundo" de "el agente está roto", que es lo que
    realmente queremos verificar acá.
    """
    for n in range(attempts):
        try:
            return req(method, path, payload)
        except urllib.error.HTTPError as e:
            retryable = e.code == 503
            if not retryable or n == attempts - 1:
                detail = json.loads(e.read()).get("detail", "")
                if retryable:
                    print(f"  ! el proveedor falló {attempts} veces: {detail}")
                raise SystemExit(f"El agente devolvió HTTP {e.code}: {detail}")
            print(f"  · proveedor no disponible, reintentando ({n + 2}/{attempts})…")
            time.sleep(3)


def expect_error(name: str, fn, status: int | None = None):
    """Verifica que la llamada falle, y devuelve el mensaje de error."""
    try:
        fn()
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read()).get("detail", "")
        if status is not None:
            check(f"{name} → HTTP {status}", e.code == status)
        else:
            check(f"{name} → error controlado", True)
        return detail
    check(f"{name} → esperaba un error", False)
    return ""


class Cleanup:
    """Acumula lo que se creó para borrarlo al final, en orden inverso."""

    def __init__(self) -> None:
        self.txs: list[int] = []
        self.goals: list[int] = []
        self.budgets: list[int] = []
        self.bills: list[int] = []

    def run(self) -> None:
        for path, ids in (
            ("/api/transactions", self.txs),
            ("/api/goals", self.goals),
            ("/api/budgets", self.budgets),
            ("/api/bills", self.bills),
        ):
            for i in ids:
                try:
                    req("DELETE", f"{path}/{i}")
                except Exception:
                    pass
        if self.txs or self.goals or self.budgets or self.bills:
            print(f"\nLimpieza: {len(self.txs)} transacciones, "
                  f"{len(self.goals)} objetivos, {len(self.budgets)} presupuestos, "
                  f"{len(self.bills)} vencimientos borrados.")


def main():
    c = Cleanup()
    try:
        _run(c)
        print("\n✅ Smoke test completo.")
    finally:
        c.run()


def _run(c: Cleanup):
    print("Esperando el servidor…")
    wait_server()

    print("\n[health]")
    health = req("GET", "/health")
    check("health endpoint responde", health.get("status") == "ok")

    print("\n[config]")
    cfg = req("GET", "/api/config")
    check(f"config expone currency={cfg['currency']}, provider={cfg['provider']}", True)
    check("config expone el umbral de alerta", 0 < cfg["budget_alert_pct"] <= 1)

    print("\n[categorías]")
    cats = req("GET", "/api/categories")
    names = {c["name"] for c in cats}
    check("existen categorías por defecto", {"Motos", "Comida"} <= names)

    print("\n[transacciones]")
    t = req("POST", "/api/transactions", {
        "type": "expense", "amount": 12345.67, "category": "Motos", "description": "smoke test"})
    c.txs.append(t["id"])
    check(f"crea transacción #{t['id']} → {t['amount_cents']} centavos", t["amount_cents"] == 1234567)
    t2 = req("POST", "/api/transactions", {"type": "income", "amount": 50000, "category": "Sueldo"})
    c.txs.append(t2["id"])
    check(f"crea ingreso #{t2['id']}", t2["type"] == "income")
    expect_error("categoría de gasto como categoría de ingreso",
                 lambda: req("POST", "/api/transactions",
                             {"type": "income", "amount": 100, "category": "Motos"}), 400)

    s = req("GET", "/api/summary")
    check("resumen coherente (balance = ingresos − gastos)",
          abs(s["balance"] - (s["total_income"] - s["total_expense"])) < 0.01)
    check("hay ingresos y gastos", s["total_income"] > 0 and s["total_expense"] > 0)

    # ------------------------------------------------------------------ metas
    print("\n[objetivos de ahorro]")
    g = req("POST", "/api/goals", {"name": "Fondo smoke", "target_amount": 1000000})
    c.goals.append(g["id"])
    check(f"crea objetivo #{g['id']} con saldo inicial 0", g["saved_cents"] == 0)
    check("objetivo nuevo está en curso", g["status"] == "en_curso")

    expect_error("nombre de objetivo duplicado (sin distinguir mayúsculas)",
                 lambda: req("POST", "/api/goals", {"name": "FONDO SMOKE", "target_amount": 10}), 409)
    expect_error("fecha límite en el pasado",
                 lambda: req("POST", "/api/goals",
                             {"name": "Viejo smoke", "target_amount": 10,
                              "target_date": "2000-01-01"}), 400)

    aporte = req("POST", "/api/transactions", {
        "type": "expense", "amount": 250000, "category": "Otros",
        "description": "aporte al objetivo", "goal": "Fondo smoke"})
    c.txs.append(aporte["id"])
    check("el movimiento queda etiquetado con el objetivo", aporte["goal"] == "Fondo smoke")

    goals = req("GET", "/api/goals")
    row = next(x for x in goals if x["id"] == g["id"])
    check("el progreso se deriva del movimiento (no de un contador aparte)",
          row["saved_cents"] == aporte["amount_cents"])
    check("lo que falta = objetivo − saldo", row["remaining_cents"] == 75000000)
    check("cuenta el aporte", row["contributions"] == 1)

    expect_error("no se puede eliminar un objetivo con movimientos asignados",
                 lambda: req("DELETE", f"/api/goals/{g['id']}"), 409)

    t3 = req("POST", "/api/transactions", {"type": "expense", "amount": 1000, "category": "Otros"})
    c.txs.append(t3["id"])
    req("DELETE", f"/api/transactions/{t3['id']}")
    c.txs.remove(t3["id"])
    req("DELETE", f"/api/transactions/{aporte['id']}")
    c.txs.remove(aporte["id"])
    check("objetivo vacío se elimina", req("DELETE", f"/api/goals/{g['id']}") is None)
    c.goals.remove(g["id"])
    expect_error("objetivo inexistente", lambda: req("DELETE", f"/api/goals/{g['id']}"), 404)

    # ----------------------------------------------------------- presupuestos
    print("\n[presupuestos mensuales]")
    b = req("POST", "/api/budgets", {"category": "Ocio", "amount": 50000})
    c.budgets.append(b["id"])
    check(f"crea presupuesto #{b['id']} para {b['category']}", b["category"] == "Ocio")
    check("recién creado está en ok", b["status"] == "ok")

    req("POST", "/api/transactions",
        {"type": "expense", "amount": 30000, "category": "Ocio", "description": "salida"})
    gasto = req("GET", "/api/transactions?categoria=Ocio&limite=1")[0]
    c.txs.append(gasto["id"])

    b = next(x for x in req("GET", "/api/budgets") if x["id"] == b["id"])
    check("el gasto del mes cuenta contra el presupuesto", b["spent_cents"] == 3000000)
    check("60% todavía no dispara la alerta (umbral 80%)", b["status"] == "ok")

    req("POST", "/api/transactions",
        {"type": "expense", "amount": 25000, "category": "Ocio", "description": "salida 2"})
    gasto2 = req("GET", "/api/transactions?categoria=Ocio&limite=1")[0]
    c.txs.append(gasto2["id"])

    b = next(x for x in req("GET", "/api/budgets") if x["id"] == b["id"])
    check("110% pasa el estado a excedido", b["status"] == "excedido")
    check("el restante es negativo", b["remaining_cents"] < 0)

    otro_mes = req("GET", "/api/budgets?mes=2000-01")[0]
    check("un mes pasado no arrastra los gastos del mes actual", otro_mes["spent_cents"] == 0)
    expect_error("mes con formato inválido", lambda: req("GET", "/api/budgets?mes=basura"), 400)

    upd = req("POST", "/api/budgets", {"category": "Ocio", "amount": 90000})
    check("reenviar la misma categoría actualiza en vez de duplicar", upd["id"] == b["id"])
    check("quedan los presupuestos en uno por categoría",
          len([x for x in req("GET", "/api/budgets") if x["category"] == "Ocio"]) == 1)
    expect_error("no se puede presupuestar una categoría de ingreso",
                 lambda: req("POST", "/api/budgets", {"category": "Sueldo", "amount": 1000}), 400)

    # ---------------------------------------------------------- vencimientos
    print("\n[vencimientos]")
    from datetime import date as _date, timedelta as _td
    hoy = _date.today()
    v1 = req("POST", "/api/bills", {
        "description": "Tarjeta smoke", "amount": 80000,
        "due_date": (hoy + _td(days=3)).isoformat(), "category": "Servicios",
        "recurrence": "monthly"})
    c.bills.append(v1["id"])
    check(f"crea vencimiento #{v1['id']} en estado proximo", v1["state"] == "proximo")
    check("days_until = 3", v1["days_until"] == 3)

    v2 = req("POST", "/api/bills", {
        "description": "Alquiler vencido smoke", "amount": 500000,
        "due_date": (hoy - _td(days=2)).isoformat(), "category": "Vivienda"})
    c.bills.append(v2["id"])
    check("vencimiento pasado queda en estado vencido", v2["state"] == "vencido")

    expect_error("no se puede cargar un vencimiento en categoría de ingreso",
                 lambda: req("POST", "/api/bills", {
                     "description": "Malo", "amount": 100,
                     "due_date": hoy.isoformat(), "category": "Sueldo"}), 400)

    pendientes = req("GET", "/api/bills")
    check("lista solo pendientes", {x["id"] for x in pendientes} >= {v1["id"], v2["id"]})

    alerts = req("GET", "/api/alerts")
    kinds = {(a["kind"], a["severity"]) for a in alerts}
    check("alertas incluyen el vencido en alta",
          ("vencimiento", "alta") in kinds)
    check("alertas incluyen el próximo en media",
          ("vencimiento", "media") in kinds)

    pago = req("POST", f"/api/bills/{v1['id']}/pay")
    check("pagar genera el gasto", pago["transaction_id"] > 0)
    c.txs.append(pago["transaction_id"])
    check("el vencimiento queda pagado", pago["bill"]["state"] == "pagado")
    check("el mensual genera el siguiente", pago["next_bill"] is not None
          and pago["next_bill"]["state"] == "pendiente")
    c.bills.append(pago["next_bill"]["id"])
    gasto_pago = req("GET", "/api/transactions?limite=100")
    check("el gasto del pago figura en movimientos",
          any(t["id"] == pago["transaction_id"] for t in gasto_pago))

    expect_error("pagar dos veces falla",
                 lambda: req("POST", f"/api/bills/{v1['id']}/pay"), 409)
    expect_error("pagar vencimiento inexistente",
                 lambda: req("POST", "/api/bills/999999/pay"), 404)
    check("eliminar vencimiento", req("DELETE", f"/api/bills/{v2['id']}") is None)
    c.bills.remove(v2["id"])
    expect_error("vencimiento inexistente",
                 lambda: req("DELETE", f"/api/bills/{v2['id']}"), 404)

    # ------------------------------------------------------------------ agente
    print(f"\n[agente — proveedor {cfg['provider']}]")
    a1 = agent_req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": "¿cuál es mi balance?"}]})
    check("devuelve una respuesta de balance no vacía", bool(a1["reply"]))
    check("sin acción pendiente", a1["pending_action"] is None)

    print("\n[agente — acción sensible → confirmación]")
    tx3 = req("POST", "/api/transactions", {"type": "expense", "amount": 9999, "category": "Motos"})
    c.txs.append(tx3["id"])
    msg = f"eliminá la transacción {tx3['id']}"
    a2 = agent_req("POST", "/api/agent/chat", {"messages": [{"role": "user", "content": msg}]})
    check("devuelve pending_action", a2["pending_action"] is not None)
    check("pending es eliminar_transaccion", a2["pending_action"]["tool"] == "eliminar_transaccion")
    check("pending apunta al id correcto", a2["pending_action"]["args"]["id"] == tx3["id"])

    print("\n[agente — confirmación de la acción]")
    a3 = agent_req("POST", "/api/agent/confirm", {
        "messages": [{"role": "user", "content": msg}],
        "pending_action": a2["pending_action"],
    })
    check("confirmación ejecuta y responde", a3["reply"] is not None and "eliminada" in a3["reply"])
    c.txs.remove(tx3["id"])

    print("\n[agente — registro grande también pide confirmación]")
    a4 = agent_req("POST", "/api/agent/chat",
                   {"messages": [{"role": "user", "content": "registrá un gasto de 75.000 en Motos"}]})
    check("pending_action = registrar_transaccion", a4["pending_action"]
          and a4["pending_action"]["tool"] == "registrar_transaccion")

    print("\n[verificación — la transacción del test quedó eliminada]")
    lista = req("GET", "/api/transactions?limite=100")
    check(f"la #{tx3['id']} no figura en la lista", all(t["id"] != tx3["id"] for t in lista))


if __name__ == "__main__":
    main()
