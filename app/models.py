"""Modelos de datos (SQLAlchemy)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # "income" | "expense"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Vehicle(Base):
    """Vehículo (moto, auto, etc.) para categorizar gastos específicos."""
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)  # ej: "Moto Honda", "Auto usado"
    kind: Mapped[str] = mapped_column(String(20))  # "moto" | "auto" | "otro"
    notes: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(10), index=True)  # "income" | "expense"
    amount_cents: Mapped[int] = mapped_column(Integer)  # montos en centavos, nunca en float
    description: Mapped[str] = mapped_column(String(200), default="")
    date: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    # Dinero separado para un objetivo de ahorro. Es opcional: si está, el
    # movimiento suma al progreso del objetivo (y sigue contando en el balance
    # general, porque el dinero efectivamente salió de tu cuenta).
    goal_id: Mapped[int | None] = mapped_column(
        ForeignKey("savings_goals.id"), nullable=True, index=True
    )
    # Tags libres para consultas flexibles (ej: ["moto", "combustible"]).
    # Se guardan como JSON string: '["tag1", "tag2"]'.
    tags: Mapped[str | None] = mapped_column(String(300), nullable=True, default=None)
    # Vehículo asociado (para gastos de moto/auto: combustible, mantenimiento, seguro).
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id"), nullable=True, index=True
    )
    # Hash de importación para deduplicación (fecha|monto|tipo|descripción normalizada).
    import_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    category: Mapped[Category] = relationship()
    goal: Mapped["SavingsGoal | None"] = relationship()
    vehicle: Mapped["Vehicle | None"] = relationship()


class SavingsGoal(Base):
    """Objetivo de ahorro: una meta con monto a juntar y fecha opcional.

    No tiene columna de "saldo": el progreso se deriva de los movimientos con
    `goal_id`. Un único libro contable, sin contador que pueda desincronizarse.
    """

    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    target_cents: Mapped[int] = mapped_column(Integer)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Budget(Base):
    """Presupuesto mensual de una categoría.

    El monto es por mes calendario y se aplica a todos los meses hasta que se
    cambie o se elimine. `category_id` es único: una categoría, un presupuesto.

    `rollover_cents` guarda lo que sobró (positivo) o faltó (negativo) del mes
    anterior y se suma al límite del mes actual para dar el "tope efectivo".
    """

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    rollover_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    category: Mapped[Category] = relationship()
