"""Esquemas Pydantic para la API REST."""
from datetime import date as Date
from typing import Literal

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


class TransactionOut(BaseModel):
    id: int
    type: str
    amount: float
    amount_cents: int
    category: str
    description: str
    date: Date


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