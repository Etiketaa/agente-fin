"""Herramientas de objetivos de ahorro.

El saldo de un objetivo no se guarda: se deriva de los movimientos que lo
tienen asignado (ver `app.analytics.goal_rows`). Así el progreso siempre
concilia con el libro de movimientos.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import analytics
from ...models import SavingsGoal
from .base import fmt, money_to_cents, parse_date


def _row_line(row: analytics.GoalRow) -> str:
    parts = [f"{row.name}: {fmt(row.saved_cents)} de {fmt(row.target_cents)} ({row.percent:.0f}%)"]
    if row.status == analytics.ALCANZADO:
        parts.append("¡objetivo alcanzado! 🎉")
    else:
        parts.append(f"faltan {fmt(row.remaining_cents)}")
    if row.target_date:
        parts.append(f"fecha límite {row.target_date.isoformat()}")
    if row.status == analytics.VENCIDO:
        parts.append("venció y quedó incompleto")
    if row.required_per_month_cents:
        parts.append(f"tenés que juntar {fmt(row.required_per_month_cents)} por mes")
    return "  - " + " | ".join(parts)


def listar_objetivos(db: Session, args: dict) -> str:
    rows = analytics.goal_rows(db)
    if not rows:
        return (
            "No hay objetivos de ahorro cargados. Si querés crear uno, pedime "
            "«creá un objetivo de ahorro llamado X por Y»."
        )
    lines = [f"Objetivos de ahorro ({len(rows)}):"]
    lines.extend(_row_line(r) for r in rows)
    if not any(r.saved_cents for r in rows):
        lines.append(
            " Ninguno tiene aportes todavía: se suman con registrar_transaccion "
            "pasando el campo 'objetivo'."
        )
    return "\n".join(lines)


def crear_objetivo(db: Session, args: dict) -> str:
    nombre = str(args.get("nombre", "")).strip()
    if not nombre:
        raise ValueError("Falta el nombre del objetivo.")
    if db.scalar(select(SavingsGoal).where(SavingsGoal.name.ilike(nombre))):
        raise ValueError(f"Ya existe un objetivo llamado '{nombre}'.")

    monto = float(args.get("monto", 0))
    if monto <= 0:
        raise ValueError("El monto objetivo debe ser mayor a cero.")

    fecha = parse_date(args.get("fecha_limite"))
    if fecha and fecha < date.today():
        raise ValueError(f"La fecha límite {fecha.isoformat()} ya pasó.")

    goal = SavingsGoal(
        name=nombre,
        target_cents=money_to_cents(monto),
        target_date=fecha,
        notes=str(args.get("notas", "")).strip(),
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    cierre = f", con fecha límite {fecha.isoformat()}" if fecha else ", sin fecha límite"
    return f"Objetivo #{goal.id} «{goal.name}» creado: meta {fmt(goal.target_cents)}{cierre}."


def eliminar_objetivo(db: Session, args: dict) -> str:
    gid = int(args.get("id", 0))
    goal = db.get(SavingsGoal, gid)
    if goal is None:
        raise ValueError(f"No existe el objetivo #{gid}.")
    saved, count = analytics.goal_contributions(db, gid)
    if count:
        raise ValueError(
            f"El objetivo «{goal.name}» tiene {count} movimiento(s) asignado(s) por "
            f"{fmt(saved)}. Para no perder ese registro, eliminá o reasigná esos "
            f"movimientos antes de borrar el objetivo."
        )
    db.delete(goal)
    db.commit()
    return f"Objetivo #{gid} «{goal.name}» eliminado."


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "listar_objetivos",
            "description": (
                "Lista los objetivos de ahorro con su progreso, lo que falta y, si "
                "tiene fecha límite, cuánto hay que juntar por mes para llegarla."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crear_objetivo",
            "description": "Crea un objetivo de ahorro (meta de dinero a juntar, con fecha límite opcional).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre corto del objetivo (ej: 'Fondo de emergencia')"},
                    "monto": {"type": "number", "description": "Monto a juntar, en la moneda local (ARS)"},
                    "fecha_limite": {"type": "string", "description": "Fecha YYYY-MM-DD para completarlo (opcional)"},
                    "notas": {"type": "string", "description": "Nota opcional"},
                },
                "required": ["nombre", "monto"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_objetivo",
            "description": (
                "Elimina un objetivo de ahorro. Falla si tiene movimientos asignados. "
                "Esta acción es sensible y requiere confirmación del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID del objetivo a eliminar"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
]

IMPLS = {
    "listar_objetivos": listar_objetivos,
    "crear_objetivo": crear_objetivo,
    "eliminar_objetivo": eliminar_objetivo,
}
