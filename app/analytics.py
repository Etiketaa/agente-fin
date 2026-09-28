"""Cálculos de dominio: objetivos de ahorro, presupuestos y alertas.

Existe una sola implementación de cada número, y la comparten la API (que la
devuelve en JSON) y las herramientas del agente (que la devuelven en texto).
Por eso el saldo que ves en la pantalla y el que te dice el asistente no
pueden divergir: salen de la misma función.

Convención: acá abajo todo se maneja en centavos enteros. La conversión a
moneda ocurre una sola vez, al serializar hacia afuera.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Budget, Category, SavingsGoal, Transaction

# Estados posibles de un presupuesto dentro de su mes.
OK = "ok"
ATENCION = "atencion"
EXCEDIDO = "excedido"

# Estados de un objetivo de ahorro.
EN_CURSO = "en_curso"
ALCANZADO = "alcanzado"
VENCIDO = "vencido"


# ---------------------------------------------------------------------------
# Períodos
# ---------------------------------------------------------------------------

def month_bounds(month: str | None) -> tuple[date, date]:
    """'YYYY-MM' → (primer día, último día). Sin argumento, el mes actual.

    Acepta también 'YYYY-MM-DD' (toma el mes de esa fecha).
    """
    if not month:
        today = date.today()
        year, mon = today.year, today.month
    else:
        parts = str(month).strip().split("-")
        if len(parts) < 2:
            raise ValueError("El mes debe tener formato YYYY-MM (ej: 2026-09).")
        try:
            year, mon = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("El mes debe tener formato YYYY-MM (ej: 2026-09).")
        if not 1 <= mon <= 12:
            raise ValueError(f"Mes inválido: {mon}. Debe ser entre 01 y 12.")
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


# ---------------------------------------------------------------------------
# Objetivos de ahorro
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GoalRow:
    id: int
    name: str
    target_cents: int
    saved_cents: int
    remaining_cents: int
    percent: float  # 0..100+, puede pasar de 100 si te pasaste del objetivo
    target_date: date | None
    notes: str
    status: str
    required_per_month_cents: int | None  # para llegar a la fecha límite
    contributions: int  # cuántos movimientos están asignados


def _goal_aggregate(db: Session, goal_id: int) -> tuple[int, int]:
    """(suma en centavos, cantidad de movimientos) de un objetivo."""
    total, count = db.execute(
        select(
            func.coalesce(func.sum(Transaction.amount_cents), 0),
            func.count(Transaction.id),
        ).where(Transaction.goal_id == goal_id)
    ).one()
    return int(total or 0), int(count or 0)


def goal_contributions(db: Session, goal_id: int) -> tuple[int, int]:
    return _goal_aggregate(db, goal_id)


def _months_until(target: date, today: date) -> float:
    """Meses aprox. que faltan hasta `target` (negativo si ya venció)."""
    return (target.year - today.year) * 12 + (target.month - today.month) + (
        target.day - today.day
    ) / 30.0


def _goal_row(db: Session, goal: SavingsGoal, today: date) -> GoalRow:
    saved, count = _goal_aggregate(db, goal.id)
    remaining = max(goal.target_cents - saved, 0)
    percent = (saved / goal.target_cents * 100) if goal.target_cents else 0.0

    required = None
    if saved >= goal.target_cents:
        status = ALCANZADO
    elif goal.target_date and goal.target_date < today:
        status = VENCIDO
    else:
        status = EN_CURSO
        if goal.target_date:
            months = _months_until(goal.target_date, today)
            if months > 0:
                required = round(remaining / months)

    return GoalRow(
        id=goal.id,
        name=goal.name,
        target_cents=goal.target_cents,
        saved_cents=saved,
        remaining_cents=remaining,
        percent=round(percent, 1),
        target_date=goal.target_date,
        notes=goal.notes or "",
        status=status,
        required_per_month_cents=required,
        contributions=count,
    )


def goal_rows(db: Session) -> list[GoalRow]:
    today = date.today()
    goals = db.scalars(select(SavingsGoal).order_by(SavingsGoal.id)).all()
    return [_goal_row(db, g, today) for g in goals]


# ---------------------------------------------------------------------------
# Presupuestos mensuales
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BudgetRow:
    id: int
    category: str
    kind: str
    limit_cents: int
    spent_cents: int
    remaining_cents: int  # negativo si ya se pasó
    percent: float
    projected_cents: int  # a ritmo actual, cuánto se gastaría al cierre del mes
    status: str
    month: str  # 'YYYY-MM' al que corresponde este row
    days_left: int


def budget_status(spent_cents: int, limit_cents: int) -> str:
    if limit_cents <= 0:
        return OK
    pct = spent_cents / limit_cents
    if pct > 1:
        return EXCEDIDO
    if pct >= get_settings().budget_alert_pct:
        return ATENCION
    return OK


def _category_spend(db: Session, category_id: int, start: date, end: date) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.category_id == category_id,
                Transaction.type == "expense",
                Transaction.date >= start,
                Transaction.date <= end,
            )
        )
        or 0
    )


def budget_rows(db: Session, month: str | None = None) -> list[BudgetRow]:
    """Presupuestos con su estado para el mes pedido (por defecto, el actual).

    La proyección solo tiene sentido en el mes en curso: para meses ya
    cerrados el "proyectado" es justamente lo gastado.
    """
    start, end = month_bounds(month)
    today = date.today()
    days_total = (end - start).days + 1
    in_current_month = start <= today <= end
    days_elapsed = (today - start).days + 1 if in_current_month else days_total

    rows: list[BudgetRow] = []
    # Un SELECT por presupuesto: son pocos (una por categoría) y el código queda
    # legible. Si alguna vez fueran cientos, se reemplaza por un GROUP BY.
    for budget in db.scalars(select(Budget).join(Category).order_by(Category.name)).all():
        spent = _category_spend(db, budget.category_id, start, end)
        if in_current_month and days_elapsed:
            projected = round(spent * days_total / days_elapsed)
        else:
            projected = spent
        limit = budget.amount_cents
        rows.append(
            BudgetRow(
                id=budget.id,
                category=budget.category.name,
                kind=budget.category.kind,
                limit_cents=limit,
                spent_cents=spent,
                remaining_cents=limit - spent,
                percent=round(spent / limit * 100, 1) if limit else 0.0,
                projected_cents=projected,
                status=budget_status(spent, limit),
                month=start.strftime("%Y-%m"),
                days_left=max((end - today).days, 0) if in_current_month else 0,
            )
        )
    return rows


def budget_alerts(rows: list[BudgetRow]) -> list[BudgetRow]:
    """Los presupuestos que requieren atención, del más urgente al menos."""
    order = {EXCEDIDO: 0, ATENCION: 1, OK: 2}
    return sorted(
        (r for r in rows if r.status != OK), key=lambda r: (order[r.status], -r.percent)
    )
