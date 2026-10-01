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
    source: str | None = Field(
        default=None, description="Procedencia del ingreso (cliente, fuente). Solo para type=income."
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
    source: str | None = None


class IncomeSourceTotal(BaseModel):
    source: str
    total: float
    total_cents: int
    count: int


class IncomeDay(BaseModel):
    date: Date
    total: float
    total_cents: int
    items: list["TransactionOut"]


class IncomeMonthOut(BaseModel):
    """Vista de ingresos del mes: total, por procedencia y por día."""
    month: str  # "YYYY-MM"
    total: float
    total_cents: int
    count: int
    by_source: list[IncomeSourceTotal]
    days: list[IncomeDay]


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
# Vencimientos
# ---------------------------------------------------------------------------

class BillCreate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, description="Monto a pagar, en unidades de moneda")
    due_date: Date = Field(description="Fecha de vencimiento YYYY-MM-DD")
    category: str = Field(description="Categoría de gasto a la que se imputa al pagar")
    recurrence: Literal["once", "monthly"] = "once"
    notes: str = ""


class BillOut(BaseModel):
    id: int
    description: str
    amount: float
    amount_cents: int
    due_date: Date
    category: str
    recurrence: str  # "once" | "monthly"
    notes: str
    state: str  # "pagado" | "vencido" | "proximo" | "pendiente"
    days_until: int  # negativo si ya venció
    paid_at: Date | None = None


class BillPayOut(BaseModel):
    bill: BillOut
    transaction_id: int
    next_bill: BillOut | None = None  # el siguiente, si era mensual


class AlertOut(BaseModel):
    severity: str  # "alta" | "media" | "baja"
    kind: str  # "vencimiento" | "presupuesto" | "objetivo" | "anomalia"
    message: str


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    # Sin min_length a propósito: la validación la hace el endpoint y devuelve
    # 400 (contrato de esta API), no el 422 genérico de Pydantic.
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str
    username: str


class UserOut(BaseModel):
    id: int
    username: str


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
