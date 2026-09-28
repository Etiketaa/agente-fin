"""Esquemas Pydantic para la API REST."""
from datetime import date as Date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CategoryOut(BaseModel):
    id: int
    name: str
    kind: str  # "income" | "expense"


class TransactionCreate(BaseModel):
    type: Literal["income", "expense"]
    amount: float = Field(gt=0, description="Monto en unidades de moneda")
    category: str
    description: str = ""
    date: Date | None = None
    goal: str | None = Field(
        default=None, description="Nombre del objetivo de ahorro al que se asigna (opcional)"
    )


class TransactionOut(BaseModel):
    id: int
    type: str
    amount: float
    amount_cents: int
    category: str
    description: str
    date: Date
    goal: str | None = None


class CategoryTotal(BaseModel):
    category: str
    kind: str
    total: float


class SummaryOut(BaseModel):
    period: str
    balance: float
    total_income: float
    total_expense: float
    count: int
    by_category: list[CategoryTotal]


# ---------------------------------------------------------------------------
# Objetivos de ahorro
# ---------------------------------------------------------------------------

class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    target_amount: float = Field(gt=0, description="Monto a juntar, en unidades de moneda")
    target_date: Date | None = None
    notes: str = ""


class GoalOut(BaseModel):
    id: int
    name: str
    target_amount: float
    target_amount_cents: int
    saved: float
    saved_cents: int
    remaining: float
    remaining_cents: int
    percent: float
    target_date: Date | None
    notes: str
    status: str  # "en_curso" | "alcanzado" | "vencido"
    required_per_month: float | None
    required_per_month_cents: int | None
    contributions: int


# ---------------------------------------------------------------------------
# Presupuestos mensuales
# ---------------------------------------------------------------------------

class BudgetCreate(BaseModel):
    category: str
    amount: float = Field(gt=0, description="Presupuesto mensual, en unidades de moneda")


class BudgetOut(BaseModel):
    id: int
    category: str
    limit: float
    limit_cents: int
    effective_limit: float
    effective_limit_cents: int
    rollover: float
    rollover_cents: int
    spent: float
    spent_cents: int
    remaining: float
    remaining_cents: int
    percent: float
    projected: float
    projected_cents: int
    status: str  # "ok" | "atencion" | "excedido"
    month: str
    days_left: int


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------

class AgentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class AgentChatRequest(BaseModel):
    messages: list[AgentMessage]


class PendingAction(BaseModel):
    tool: str
    args: dict
    summary: str


class AgentConfirmRequest(BaseModel):
    messages: list[AgentMessage]
    pending_action: PendingAction


class AgentResponse(BaseModel):
    reply: str | None = None
    pending_action: PendingAction | None = None
