"""Herramientas de presupuesto mensual por categoría y sus alertas."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import analytics
from ...models import Budget
from .base import find_category, fmt, money_to_cents

_ICONO = {analytics.EXCEDIDO: "🔴", analytics.ATENCION: "🟡", analytics.OK: "🟢"}


def _row_line(row: analytics.BudgetRow) -> str:
    partes = [
        f"{_ICONO[row.status]} {row.category}: {fmt(row.spent_cents)} de {fmt(row.limit_cents)} "
        f"({row.percent:.0f}%)"
    ]
    if row.remaining_cents < 0:
        partes.append(f"te pasaste por {fmt(-row.remaining_cents)}")
    else:
        partes.append(f"quedan {fmt(row.remaining_cents)}")
    if row.days_left:
        partes.append(f"faltan {row.days_left} días del mes")
        if row.projected_cents > row.limit_cents and row.status != analytics.EXCEDIDO:
            partes.append(f"a este ritmo vas a terminar el mes en {fmt(row.projected_cents)}")
    return "  - " + " | ".join(partes)


def listar_presupuestos(db: Session, args: dict) -> str:
    # Si el mes viene mal formado, month_bounds lanza ValueError y el bucle del
    # agente se lo devuelve al modelo como error, para que lo corrija solo.
    mes = str(args.get("mes", "")).strip() or None
    rows = analytics.budget_rows(db, mes)
    if not rows:
        return (
            "No hay presupuestos cargados. Podés crear uno con "
            "«poné un presupuesto de 300000 para Comida»."
        )
    etiqueta = rows[0].month
    alertas = analytics.budget_alerts(rows)
    lines = [f"Presupuestos de {etiqueta} ({len(rows)}):"]
    lines.extend(_row_line(r) for r in rows)
    if alertas:
        lines.append(
            " Atención: " + ", ".join(f"{r.category} ({r.status})" for r in alertas)
        )
    return "\n".join(lines)


def definir_presupuesto(db: Session, args: dict) -> str:
    cat = find_category(db, str(args.get("categoria", "")), "expense")
    monto = float(args.get("monto", 0))
    if monto <= 0:
        raise ValueError("El monto del presupuesto debe ser mayor a cero.")
    cents = money_to_cents(monto)

    budget = db.scalar(select(Budget).where(Budget.category_id == cat.id))
    if budget is None:
        budget = Budget(category_id=cat.id, amount_cents=cents)
        db.add(budget)
        db.commit()
        db.refresh(budget)
        return f"Presupuesto creado: {fmt(cents)} por mes para {cat.name}."

    anterior = budget.amount_cents
    budget.amount_cents = cents
    db.commit()
    return (
        f"Presupuesto de {cat.name} actualizado: {fmt(anterior)} → {fmt(cents)} por mes."
    )


def eliminar_presupuesto(db: Session, args: dict) -> str:
    bid = int(args.get("id", 0))
    budget = db.get(Budget, bid)
    if budget is None:
        raise ValueError(f"No existe el presupuesto #{bid}.")
    nombre = budget.category.name
    db.delete(budget)
    db.commit()
    return f"Presupuesto de {nombre} eliminado."


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "listar_presupuestos",
            "description": (
                "Lista los presupuestos mensuales por categoría con lo gastado del mes, "
                "lo que queda y una alerta si se está acercando o pasó el límite. "
                "Usala también cuando te pregunten cómo venís con los gastos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mes": {"type": "string", "description": "Mes a consultar en formato YYYY-MM (opcional, por defecto el actual)"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "definir_presupuesto",
            "description": (
                "Define el presupuesto mensual de una categoría de gasto. Si la categoría "
                "ya tiene presupuesto, lo actualiza al monto nuevo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {"type": "string", "description": "Nombre exacto de la categoría de gasto"},
                    "monto": {"type": "number", "description": "Presupuesto mensual en la moneda local (ARS)"},
                },
                "required": ["categoria", "monto"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_presupuesto",
            "description": (
                "Elimina el presupuesto mensual de una categoría. "
                "Esta acción es sensible y requiere confirmación del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID del presupuesto a eliminar"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
]

IMPLS = {
    "listar_presupuestos": listar_presupuestos,
    "definir_presupuesto": definir_presupuesto,
    "eliminar_presupuesto": eliminar_presupuesto,
}
