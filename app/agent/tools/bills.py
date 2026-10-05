"""Herramientas de vencimientos y del centro de alertas.

El estado de un vencimiento no se guarda: se deriva de `paid_at` y de la
fecha (ver `app.analytics.bill_rows`). Pagar genera el gasto real y, si es
mensual, crea el vencimiento siguiente automáticamente.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import analytics
from ...models import Bill, Transaction
from .base import find_category, fmt, money_to_cents, parse_date
from .transactions import resolve_account

_ICONO = {
    analytics.PAGADO: "✅",
    analytics.BILL_VENCIDO: "🔴",
    analytics.PROXIMO: "🟡",
    analytics.PENDIENTE: "⚪",
}


def _row_line(row: analytics.BillRow) -> str:
    if row.state == analytics.PAGADO:
        cuando = "pagado"
    elif row.state == analytics.BILL_VENCIDO:
        cuando = f"venció hace {-row.days_until} día(s)"
    elif row.days_until == 0:
        cuando = "vence hoy"
    elif row.days_until == 1:
        cuando = "vence mañana"
    else:
        cuando = f"vence en {row.days_until} días ({row.due_date.isoformat()})"
    rec = " (mensual)" if row.recurrence == "monthly" else ""
    return (
        f"  - {_ICONO[row.state]} #{row.id} «{row.description}»{rec}: "
        f"{fmt(row.amount_cents)} | {cuando} | {row.category}"
    )


def listar_vencimientos(db: Session, args: dict, user_id: int) -> str:
    todos = bool(args.get("todos", False))
    rows = analytics.bill_rows(db, user_id, solo_pendientes=not todos)
    if not rows:
        return (
            "No hay vencimientos pendientes. Si querés cargar uno, pedime "
            "«agregá un vencimiento de luz por 45000 para el 10 del mes que viene»."
        )
    lines = [f"Vencimientos pendientes ({len(rows)}):"]
    lines.extend(_row_line(r) for r in rows)
    return "\n".join(lines)


def crear_vencimiento(db: Session, args: dict, user_id: int) -> str:
    descripcion = str(args.get("descripcion", "")).strip()
    if not descripcion:
        raise ValueError("Falta la descripción del vencimiento.")
    monto = float(args.get("monto", 0))
    if monto <= 0:
        raise ValueError("El monto del vencimiento debe ser mayor a cero.")
    fecha = parse_date(args.get("fecha"))
    if fecha is None:
        raise ValueError("Falta la fecha de vencimiento (formato YYYY-MM-DD).")
    cat = find_category(db, user_id, str(args.get("categoria", "")), "expense")
    rec = str(args.get("recurrencia", "once")).strip().lower() or "once"
    if rec not in ("once", "monthly"):
        raise ValueError("La recurrencia debe ser 'once' (una vez) o 'monthly' (mensual).")

    bill = Bill(
        user_id=user_id,
        description=descripcion,
        amount_cents=money_to_cents(monto),
        due_date=fecha,
        category_id=cat.id,
        recurrence=rec,
        notes=str(args.get("notas", "")).strip(),
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    rec_txt = ", mensual" if rec == "monthly" else ""
    return (
        f"Vencimiento #{bill.id} «{bill.description}» creado: "
        f"{fmt(bill.amount_cents)} para el {fecha.isoformat()}{rec_txt} ({cat.name})."
    )


def pagar_vencimiento(db: Session, args: dict, user_id: int) -> str:
    bid = int(args.get("id", 0))
    bill = db.get(Bill, bid)
    if bill is None or bill.user_id != user_id:
        raise ValueError(f"No existe el vencimiento #{bid}.")
    if bill.paid_at is not None:
        raise ValueError(f"El vencimiento «{bill.description}» ya está pagado.")

    # El pago sale de alguna billetera; si no se indica, va a «General».
    cuenta_id = resolve_account(db, user_id, str(args.get("billetera", "") or "")).id

    t = Transaction(
        user_id=user_id,
        type="expense",
        amount_cents=bill.amount_cents,
        category_id=bill.category_id,
        description=f"Pago: {bill.description}",
        date=date.today(),
        # El pago sale de alguna billetera; si no se indica, va a «General».
        cuenta_id=cuenta_id,
    )
    db.add(t)
    bill.paid_at = date.today()

    extra = ""
    if bill.recurrence == "monthly":
        siguiente = Bill(
            user_id=user_id,
            description=bill.description,
            amount_cents=bill.amount_cents,
            due_date=analytics.add_months(bill.due_date),
            category_id=bill.category_id,
            recurrence="monthly",
            notes=bill.notes,
        )
        db.add(siguiente)
        db.flush()
        extra = f" Se generó el siguiente vencimiento (#{siguiente.id}) para el {siguiente.due_date.isoformat()}."
    db.commit()
    return (
        f"Vencimiento «{bill.description}» pagado: gasto de "
        f"{fmt(bill.amount_cents)} en {bill.category.name} (movimiento #{t.id}).{extra}"
    )


def eliminar_vencimiento(db: Session, args: dict, user_id: int) -> str:
    bid = int(args.get("id", 0))
    bill = db.get(Bill, bid)
    if bill is None or bill.user_id != user_id:
        raise ValueError(f"No existe el vencimiento #{bid}.")
    nombre = bill.description
    db.delete(bill)
    db.commit()
    return f"Vencimiento #{bid} «{nombre}» eliminado."


def listar_alertas(db: Session, args: dict, user_id: int) -> str:
    alerts = analytics.all_alerts(db, user_id)
    if not alerts:
        return "✅ Sin alertas: nada vencido, presupuestos en orden y metas al día."
    lines = [f"Alertas ({len(alerts)}), las más urgentes primero:"]
    for a in alerts:
        lines.append(f"  - [{a.severity}] {a.message}")
    return "\n".join(lines)


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "listar_vencimientos",
            "description": (
                "Lista los vencimientos pendientes (pagos futuros: tarjeta, alquiler, "
                "seguro...) con su estado: vencido, próximo (7 días o menos) o pendiente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {"type": "boolean", "description": "Incluir también los ya pagados (por defecto solo pendientes)"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crear_vencimiento",
            "description": (
                "Carga un vencimiento: un pago futuro con fecha (ej: tarjeta, alquiler, "
                "seguro de la moto). Acepta recurrencia 'once' o 'monthly'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string", "description": "Qué hay que pagar (ej: 'Tarjeta Visa', 'Alquiler')"},
                    "monto": {"type": "number", "description": "Monto a pagar, en la moneda local (ARS)"},
                    "fecha": {"type": "string", "description": "Fecha de vencimiento YYYY-MM-DD"},
                    "categoria": {"type": "string", "description": "Categoría de gasto (acepta coincidencias parciales)"},
                    "recurrencia": {"type": "string", "description": "'once' (una vez) o 'monthly' (todos los meses). Por defecto 'once'"},
                    "notas": {"type": "string", "description": "Nota opcional"},
                },
                "required": ["descripcion", "monto", "fecha", "categoria"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pagar_vencimiento",
            "description": (
                "Marca un vencimiento como pagado y genera el gasto correspondiente. "
                "Si es mensual, crea automáticamente el vencimiento del mes siguiente. "
                "Esta acción es sensible y requiere confirmación del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID del vencimiento a pagar"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_vencimiento",
            "description": (
                "Elimina un vencimiento. "
                "Esta acción es sensible y requiere confirmación del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID del vencimiento a eliminar"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_alertas",
            "description": (
                "Muestra el centro de alertas: vencimientos vencidos o próximos, "
                "presupuestos en atención o excedidos, objetivos vencidos o por "
                "vencer y gastos fuera de lo habitual. Usala cuando pregunten "
                "'¿qué tengo pendiente?' o '¿hay algo que requiera atención?'."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

IMPLS = {
    "listar_vencimientos": listar_vencimientos,
    "crear_vencimiento": crear_vencimiento,
    "pagar_vencimiento": pagar_vencimiento,
    "eliminar_vencimiento": eliminar_vencimiento,
    "listar_alertas": listar_alertas,
}
