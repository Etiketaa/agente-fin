"""Endpoints REST de la aplicación."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import analytics
from .agent.agent import run_agent
from .agent.provider import ProviderError, get_provider
from .agent.tools import cents_to_money, money_to_cents
from .config import get_settings
from .db import get_db
from .models import Budget, Category, SavingsGoal, Transaction
from .schemas import (
    AgentChatRequest,
    AgentConfirmRequest,
    AgentResponse,
    BudgetCreate,
    BudgetOut,
    CategoryOut,
    CategoryTotal,
    GoalCreate,
    GoalOut,
    SummaryOut,
    TransactionCreate,
    TransactionOut,
)

router = APIRouter(prefix="/api")


def _parse_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"Fecha inválida: '{value}'. Usá YYYY-MM-DD.")


def _find_category(db: Session, name: str, kind: str | None = None) -> Category:
    cat = db.scalar(select(Category).where(func.lower(Category.name) == name.strip().lower()))
    if cat is None:
        raise HTTPException(404, f"Categoría no encontrada: {name}")
    if kind and cat.kind != kind:
        raise HTTPException(400, f"La categoría '{cat.name}' es de {cat.kind}, no de {kind}")
    return cat


def _to_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        type=t.type,
        amount=cents_to_money(t.amount_cents),
        amount_cents=t.amount_cents,
        category=t.category.name,
        description=t.description,
        date=t.date,
        goal=t.goal.name if t.goal else None,
    )


def _goal_out(row: analytics.GoalRow) -> GoalOut:
    return GoalOut(
        id=row.id,
        name=row.name,
        target_amount=cents_to_money(row.target_cents),
        target_amount_cents=row.target_cents,
        saved=cents_to_money(row.saved_cents),
        saved_cents=row.saved_cents,
        remaining=cents_to_money(row.remaining_cents),
        remaining_cents=row.remaining_cents,
        percent=row.percent,
        target_date=row.target_date,
        notes=row.notes,
        status=row.status,
        required_per_month=(
            cents_to_money(row.required_per_month_cents)
            if row.required_per_month_cents is not None
            else None
        ),
        required_per_month_cents=row.required_per_month_cents,
        contributions=row.contributions,
    )


def _budget_out(row: analytics.BudgetRow) -> BudgetOut:
    return BudgetOut(
        id=row.id,
        category=row.category,
        limit=cents_to_money(row.limit_cents),
        limit_cents=row.limit_cents,
        spent=cents_to_money(row.spent_cents),
        spent_cents=row.spent_cents,
        remaining=cents_to_money(row.remaining_cents),
        remaining_cents=row.remaining_cents,
        percent=row.percent,
        projected=cents_to_money(row.projected_cents),
        projected_cents=row.projected_cents,
        status=row.status,
        month=row.month,
        days_left=row.days_left,
    )


@router.get("/config")
def get_config():
    s = get_settings()
    provider = get_provider()
    return {
        "currency": s.currency,
        "provider": s.llm_provider,
        "model": provider.model,
        "sensitive_amount": s.sensitive_amount,
        "budget_alert_pct": s.budget_alert_pct,
    }


# ---------------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------------

@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.kind, Category.name)).all()


# ---------------------------------------------------------------------------
# Objetivos de ahorro
# ---------------------------------------------------------------------------

@router.get("/goals", response_model=list[GoalOut])
def list_goals(db: Session = Depends(get_db)):
    return [_goal_out(r) for r in analytics.goal_rows(db)]


@router.post("/goals", response_model=GoalOut, status_code=201)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)):
    nombre = payload.name.strip()
    if not nombre:
        raise HTTPException(400, "El nombre del objetivo no puede estar vacío.")
    if db.scalar(select(SavingsGoal).where(SavingsGoal.name.ilike(nombre))):
        raise HTTPException(409, f"Ya existe un objetivo llamado '{nombre}'.")
    if payload.target_date and payload.target_date < date.today():
        raise HTTPException(400, f"La fecha límite {payload.target_date} ya pasó.")
    goal = SavingsGoal(
        name=nombre,
        target_cents=money_to_cents(payload.target_amount),
        target_date=payload.target_date,
        notes=payload.notes.strip(),
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    row = next(r for r in analytics.goal_rows(db) if r.id == goal.id)
    return _goal_out(row)


@router.delete("/goals/{gid}", status_code=204)
def delete_goal(gid: int, db: Session = Depends(get_db)):
    goal = db.get(SavingsGoal, gid)
    if goal is None:
        raise HTTPException(404, f"No existe el objetivo #{gid}")
    _, count = analytics.goal_contributions(db, gid)
    if count:
        # Desvincular en silencio dejaría movimientos apuntando a un objetivo
        # inexistente: preferimos rechazar que perder trazabilidad del dinero.
        raise HTTPException(
            409,
            f"El objetivo «{goal.name}» tiene {count} movimiento(s) asignado(s). "
            f"Eliminá o reasigná esos movimientos antes de borrar el objetivo.",
        )
    db.delete(goal)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Presupuestos mensuales
# ---------------------------------------------------------------------------

@router.get("/budgets", response_model=list[BudgetOut])
def list_budgets(mes: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        rows = analytics.budget_rows(db, mes)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return [_budget_out(r) for r in rows]


@router.post("/budgets", response_model=BudgetOut, status_code=201)
def upsert_budget(payload: BudgetCreate, db: Session = Depends(get_db)):
    cat = _find_category(db, payload.category, "expense")
    cents = money_to_cents(payload.amount)
    budget = db.scalar(select(Budget).where(Budget.category_id == cat.id))
    if budget is None:
        budget = Budget(category_id=cat.id, amount_cents=cents)
        db.add(budget)
        db.commit()
        db.refresh(budget)
    else:
        budget.amount_cents = cents
        db.commit()
    row = next(r for r in analytics.budget_rows(db) if r.id == budget.id)
    return _budget_out(row)


@router.delete("/budgets/{bid}", status_code=204)
def delete_budget(bid: int, db: Session = Depends(get_db)):
    budget = db.get(Budget, bid)
    if budget is None:
        raise HTTPException(404, f"No existe el presupuesto #{bid}")
    db.delete(budget)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Transacciones
# ---------------------------------------------------------------------------

@router.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db)):
    cat = _find_category(db, payload.category)
    if cat.kind != payload.type:
        raise HTTPException(400, f"La categoría '{cat.name}' es de {cat.kind}, no de {payload.type}")

    goal = None
    if payload.goal and payload.goal.strip():
        goal = db.scalar(select(SavingsGoal).where(SavingsGoal.name.ilike(payload.goal.strip())))
        if goal is None:
            disponibles = ", ".join(
                g.name for g in db.scalars(select(SavingsGoal).order_by(SavingsGoal.name)).all()
            )
            raise HTTPException(
                404, f"No existe el objetivo '{payload.goal}'. Disponibles: {disponibles or '(ninguno)'}"
            )

    t = Transaction(
        type=payload.type,
        amount_cents=money_to_cents(payload.amount),
        category_id=cat.id,
        goal_id=goal.id if goal else None,
        description=payload.description.strip(),
        date=payload.date or date.today(),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_out(t)


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    objetivo: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    limite: int = 50,
    db: Session = Depends(get_db),
):
    q = select(Transaction).join(Category)
    if tipo:
        q = q.where(Transaction.type == tipo)
    if categoria:
        q = q.where(func.lower(Category.name) == categoria.strip().lower())
    if objetivo:
        goal = db.scalar(select(SavingsGoal).where(SavingsGoal.name.ilike(objetivo.strip())))
        if goal is None:
            raise HTTPException(404, f"No existe el objetivo '{objetivo}'")
        q = q.where(Transaction.goal_id == goal.id)
    d = _parse_iso(desde)
    if d:
        q = q.where(Transaction.date >= d)
    h = _parse_iso(hasta)
    if h:
        q = q.where(Transaction.date <= h)
    rows = db.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limite)).all()
    return [_to_out(t) for t in rows]


@router.delete("/transactions/{tid}", status_code=204)
def delete_transaction(tid: int, db: Session = Depends(get_db)):
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, f"No existe la transacción #{tid}")
    db.delete(t)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=SummaryOut)
def summary(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = select(Transaction).join(Category)
    d = _parse_iso(desde)
    if d:
        q = q.where(Transaction.date >= d)
    h = _parse_iso(hasta)
    if h:
        q = q.where(Transaction.date <= h)
    rows = db.scalars(q).all()

    total_income = sum(t.amount_cents for t in rows if t.type == "income")
    total_expense = sum(t.amount_cents for t in rows if t.type == "expense")

    by_category: dict[str, dict] = {}
    for t in rows:
        item = by_category.setdefault(t.category.name, {"kind": t.category.kind, "total_cents": 0})
        item["total_cents"] += t.amount_cents

    period = "personalizado"
    if d and h:
        period = f"{d.isoformat()} → {h.isoformat()}"
    elif d:
        period = f"desde {d.isoformat()}"
    elif h:
        period = f"hasta {h.isoformat()}"
    else:
        period = "todo el historial"

    return SummaryOut(
        period=period,
        balance=cents_to_money(total_income - total_expense),
        total_income=cents_to_money(total_income),
        total_expense=cents_to_money(total_expense),
        count=len(rows),
        by_category=[
            CategoryTotal(category=name, kind=item["kind"], total=cents_to_money(item["total_cents"]))
            for name, item in sorted(by_category.items(), key=lambda kv: -kv[1]["total_cents"])
        ],
    )


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------

def _run_agent_safe(messages: list[dict], db: Session, pre_confirmed: dict | None = None):
    """Corre el agente traduciendo una falla del proveedor a un 503 entendible.

    El proveedor es un servicio externo: una caída o un 500 suyo no es un error
    de esta app. Sin esto, FastAPI devolvía un 500 con traceback y el chat
    quedaba sin explicación.
    """
    try:
        return run_agent(messages, db, pre_confirmed=pre_confirmed)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

@router.post("/agent/chat", response_model=AgentResponse)
def agent_chat(payload: AgentChatRequest, db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    return _run_agent_safe(messages, db)


@router.post("/agent/confirm", response_model=AgentResponse)
def agent_confirm(payload: AgentConfirmRequest, db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    pending = {
        "tool": payload.pending_action.tool,
        "args": payload.pending_action.args,
    }
    return _run_agent_safe(messages, db, pre_confirmed=pending)
