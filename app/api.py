"""Endpoints REST de la aplicación."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent.agent import run_agent
from .agent.provider import get_provider
from .agent.tools import cents_to_money, money_to_cents
from .config import get_settings
from .db import get_db
from .models import Category, Transaction
from .schemas import (
    AgentChatRequest,
    AgentConfirmRequest,
    AgentResponse,
    CategoryOut,
    CategoryTotal,
    SummaryOut,
    TransactionCreate,
    TransactionOut,
)

router = APIRouter(prefix="/api")


def _parse_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def _to_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        type=t.type,
        amount=cents_to_money(t.amount_cents),
        amount_cents=t.amount_cents,
        category=t.category.name,
        description=t.description,
        date=t.date,
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
    }


# ---------------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------------

@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.kind, Category.name)).all()


# ---------------------------------------------------------------------------
# Transacciones
# ---------------------------------------------------------------------------

@router.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db)):
    cat = db.scalar(select(Category).where(func.lower(Category.name) == payload.category.strip().lower()))
    if cat is None:
        raise HTTPException(404, f"Categoría no encontrada: {payload.category}")
    if cat.kind != payload.type:
        raise HTTPException(400, f"La categoría '{cat.name}' es de {cat.kind}, no de {payload.type}")
    t = Transaction(
        type=payload.type,
        amount_cents=money_to_cents(payload.amount),
        category_id=cat.id,
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
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    limite: int = 50,
    db: Session = Depends(get_db),
):
    q = select(Transaction).join(Category)
    if tipo:
        q = q.where(Transaction.type == tipo)
    if categoria:
        q = q.where(func.lower(Category.name) == func.lower(categoria))
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

@router.post("/agent/chat", response_model=AgentResponse)
def agent_chat(payload: AgentChatRequest, db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    return run_agent(messages, db)


@router.post("/agent/confirm", response_model=AgentResponse)
def agent_confirm(payload: AgentConfirmRequest, db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    pending = {
        "tool": payload.pending_action.tool,
        "args": payload.pending_action.args,
    }
    return run_agent(messages, db, pre_confirmed=pending)