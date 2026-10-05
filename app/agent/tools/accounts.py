"""Herramientas de billeteras: dónde está la plata y cuánto hay en total.

El saldo que devuelve `listar_billeteras` es el mismo derivado que muestra el
panel (`analytics.account_rows`): si el chat y la pantalla no pueden dar números
distintos, es porque no hay dos cálculos.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import analytics
from ...models import Account, Transaction
from .base import fmt, money_to_cents


def listar_billeteras(db: Session, args: dict, user_id: int) -> str:
    from ...seed import DEFAULT_ACCOUNT_NAME

    rows = analytics.account_rows(db, user_id)
    reales = [r for r in rows if r.name != DEFAULT_ACCOUNT_NAME]
    if not rows:
        return (
            "No tenés billeteras cargadas. Podés crear una con «creá la billetera "
            "Mercado Pago tipo digital con saldo 50000»."
        )
    lineas = ["Billeteras (saldo = apertura + movimientos):"]
    for r in rows:
        movs = f", {r.movimientos} movimiento(s)" if r.movimientos else ""
        ultimo = f", último: {r.ultimo_movimiento.isoformat()}" if r.ultimo_movimiento else ""
        etiqueta = " [general: movimientos sin billetera asignada]" if r.name == DEFAULT_ACCOUNT_NAME else ""
        lineas.append(
            f"  - #{r.id} {r.name} ({r.kind}){etiqueta}: {fmt(r.balance_cents)}{movs}{ultimo}"
        )
    total = analytics.total_cents(db, user_id)
    lineas.append(f"Patrimonio total: {fmt(total)} ({len(rows)} billeteras).")
    if not reales:
        lineas.append(
            "Ojo: todavía no cargaste ninguna billetera real, así que ese total es sólo "
            "la diferencia entre tus ingresos y gastos registrados, no tu plata."
        )
    return "\n".join(lineas)


def crear_billetera(db: Session, args: dict, user_id: int) -> str:
    from ...seed import DEFAULT_ACCOUNT_NAME

    nombre = str(args.get("nombre", "")).strip()
    if not nombre:
        raise ValueError("El nombre de la billetera no puede estar vacío.")
    if nombre.lower() == DEFAULT_ACCOUNT_NAME.lower():
        raise ValueError(
            f"«{DEFAULT_ACCOUNT_NAME}» ya existe: es la billetera donde caen los "
            "movimientos sin asignar."
        )
    tipo = str(args.get("tipo", "otro")).strip().lower() or "otro"
    if tipo not in ("banco", "digital", "efectivo", "otro"):
        raise ValueError("Tipo debe ser: banco, digital, efectivo u otro.")

    existe = db.scalar(
        select(Account).where(
            Account.user_id == user_id, func.lower(Account.name) == nombre.lower()
        )
    )
    if existe:
        raise ValueError(f"Ya existe una billetera llamada '{nombre}' (#{existe.id}).")

    try:
        saldo = money_to_cents(float(args.get("saldo", 0)))
    except (TypeError, ValueError):
        raise ValueError("El saldo debe ser un número (podés cargar 0 si no lo sabés).")

    acc = Account(
        user_id=user_id,
        name=nombre,
        kind=tipo,
        apertura_cents=saldo,
        notes=str(args.get("notas", "")).strip(),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return (
        f"Billetera «{acc.name}» ({acc.kind}) creada con saldo de partida "
        f"{fmt(acc.apertura_cents)} (#{acc.id})."
    )


def ajustar_saldo_billetera(db: Session, args: dict, user_id: int) -> str:
    """Conciliación: el saldo derivado pasa a ser el número real declarado."""
    nombre = str(args.get("nombre", "")).strip()
    if not nombre:
        raise ValueError("Falta el nombre de la billetera a ajustar.")
    acc = db.scalar(
        select(Account).where(
            Account.user_id == user_id,
            Account.name.ilike(nombre),
        )
    )
    if acc is None:
        nombres = ", ".join(
            a.name
            for a in db.scalars(
                select(Account).where(Account.user_id == user_id).order_by(Account.name)
            ).all()
        )
        raise ValueError(f"No existe la billetera '{nombre}'. Tenés: {nombres}.")

    try:
        declarado = money_to_cents(float(args.get("saldo", 0)))
    except (TypeError, ValueError):
        raise ValueError("El saldo debe ser un número.")

    antes = analytics._neto_por_cuenta(db, user_id).get(acc.id, (0, 0, None))[0]
    anterior = acc.apertura_cents + antes
    analytics.reconcile_account(db, acc, declarado, user_id)
    nuevo = acc.apertura_cents + antes
    return (
        f"Saldo de «{acc.name}» ajustado: {fmt(anterior)} → {fmt(nuevo)} "
        f"(declaraste {fmt(declarado)}; desvío corregido {fmt(declarado - anterior)})."
    )


def eliminar_billetera(db: Session, args: dict, user_id: int) -> str:
    from ...seed import DEFAULT_ACCOUNT_NAME, default_account

    nombre = str(args.get("nombre", "")).strip()
    acc = db.scalar(
        select(Account).where(Account.user_id == user_id, Account.name.ilike(nombre))
    )
    if acc is None:
        raise ValueError(f"No existe la billetera '{nombre}'.")
    if acc.name == DEFAULT_ACCOUNT_NAME:
        raise ValueError(
            f"«{DEFAULT_ACCOUNT_NAME}» no se puede borrar: recibe los movimientos sin asignar."
        )

    row = next(r for r in analytics.account_rows(db, user_id) if r.id == acc.id)
    nombre_acc, movimientos = acc.name, row.movimientos
    if movimientos:
        # Sus movimientos pasan a «General»: no se borra historia y el
        # patrimonio sigue cuadrando.
        general = default_account(db, user_id)
        movs = db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id, Transaction.cuenta_id == acc.id
            )
        ).all()
        for t in movs:
            t.cuenta_id = general.id
    db.delete(acc)
    db.commit()
    extra = f" Sus {movimientos} movimiento(s) pasaron a «General»." if movimientos else ""
    return f"Billetera «{nombre_acc}» eliminada.{extra}"


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "listar_billeteras",
            "description": (
                "Lista las billeteras con su saldo actual (apertura + movimientos) y el "
                "patrimonio total. Usala cuando te pregunten cuánta plata hay en total o "
                "dónde está."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crear_billetera",
            "description": (
                "Crea una billetera (Mercado Pago, banco, efectivo...). El 'saldo' es el "
                "saldo REAL que tiene hoy: queda como base y de ahí en adelante se mueve "
                "sola con cada movimiento. Requiere confirmación."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre de la billetera (ej: 'Mercado Pago')"},
                    "tipo": {"type": "string", "enum": ["banco", "digital", "efectivo", "otro"], "description": "Tipo de billetera"},
                    "saldo": {"type": "number", "description": "Saldo actual real (podés usar 0 si no lo sabés)"},
                    "notas": {"type": "string", "description": "Notas opcionales"},
                },
                "required": ["nombre", "tipo"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ajustar_saldo_billetera",
            "description": (
                "Ajusta el saldo de una billetera al número real que informa la app del banco. "
                "Es una conciliación: no borra movimientos, sólo deja de desfasar el total. "
                "Requiere confirmación."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre exacto de la billetera"},
                    "saldo": {"type": "number", "description": "Saldo real actual según el banco"},
                },
                "required": ["nombre", "saldo"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_billetera",
            "description": (
                "Elimina una billetera. Sus movimientos pasan a «General» (no se borra "
                "historia). Requiere confirmación."
            ),
            "parameters": {
                "type": "object",
                "properties": {"nombre": {"type": "string", "description": "Nombre exacto de la billetera"}},
                "required": ["nombre"],
                "additionalProperties": False,
            },
        },
    },
]

IMPLS = {
    "listar_billeteras": listar_billeteras,
    "crear_billetera": crear_billetera,
    "ajustar_saldo_billetera": ajustar_saldo_billetera,
    "eliminar_billetera": eliminar_billetera,
}