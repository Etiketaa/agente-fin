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
    cuenta: str | None = Field(
        default=None,
        description="Billetera del movimiento (opcional). Si no viene, cae en «General».",
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
    cuenta: str | None = None  # billetera imputada


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
    # Dinero comprometido: IGNORA `desde`/`hasta` a propósito, porque un
    # vencimiento no pertenece a un período, vence en una fecha. Es lo que ya
    # sabés que tenés que pagar, y lo que hay que restarle al patrimonio para
    # saber cuánto está realmente disponible.
    comprometido: float
    comprometido_cents: int
    comprometido_mes: float
    comprometido_mes_cents: int
    vencido: float
    vencido_cents: int
    disponible: float
    disponible_cents: int
    # Quantos vencimientos forman el comprometido. Sin el número, el texto
    # "450.000 comprometidos" no dice si es un pago grande o cinco chicos.
    comprometido_count: int
    vencido_count: int


# ---------------------------------------------------------------------------
# Objetivos de ahorro
# ---------------------------------------------------------------------------

class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    target_amount: float = Field(gt=0, description="Monto a juntar, en unidades de moneda")
    target_date: Date | None = None
    kind: Literal["ahorro", "recaudacion"] = "ahorro"
    notes: str = ""


class GoalOut(BaseModel):
    id: int
    name: str
    kind: str  # "ahorro" | "recaudacion"
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
# Billeteras (patrimonio)
# ---------------------------------------------------------------------------

class AccountCreate(BaseModel):
    """Al crear, `saldo` es el saldo real que tiene la billetera HOY: queda como
    apertura y de ahí en adelante se mueve sola con cada movimiento."""

    name: str = Field(min_length=1, max_length=80)
    kind: Literal["banco", "digital", "efectivo", "otro"] = "otro"
    # admite negativo: una tarjeta en rojo es un saldo negativo real
    saldo: float = Field(default=0.0, allow_inf_nan=False)
    notes: str = Field(default="", max_length=200)


class AccountUpdate(BaseModel):
    """Actualización parcial: mandás solo lo que cambia.

    Mandar `saldo` es una conciliación: el saldo derivado pasa a ser exactamente
    ese número (no borra movimientos ni inventa los que faltaban).
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: Literal["banco", "digital", "efectivo", "otro"] | None = None
    saldo: float | None = Field(default=None, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=200)


class AccountOut(BaseModel):
    id: int
    name: str
    kind: str
    es_default: bool = False  # True = billetera «General» (movimientos sin asignar)
    apertura: float  # saldo de partida
    apertura_cents: int
    balance: float  # apertura + movimientos (derivado)
    balance_cents: int
    movimientos: int
    ultimo_movimiento: str | None = None  # ISO
    notes: str
    updated_at: str | None = None  # ISO; la UI avisa si el saldo es viejo


class AccountsOut(BaseModel):
    accounts: list[AccountOut]
    total: float  # patrimonio: suma de los saldos
    total_cents: int
    count: int


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
