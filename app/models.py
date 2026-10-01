"""Modelos de datos (SQLAlchemy).

Regla multiusuario: TODA tabla de dominio tiene `user_id` (FK a users, con
borrado en cascada). Ningún query puede filtrar sin `user_id`: los datos de
un usuario nunca son visibles para otro, ni siquiera por ID adivinado.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    """Usuario de la app. Cada usuario ve solo sus propios datos.

    El hash de contraseña usa PBKDF2-SHA256 de la stdlib (sin dependencias
    nuevas). Los tokens de sesión se guardan hasheados: si alguien lee la
    base, no obtiene sesiones válidas.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserSession(Base):
    """Sesión iniciada: un token opaco por login (revocable con logout)."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))  # "income" | "expense"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Vehicle(Base):
    """Vehículo (moto, auto, etc.) para categorizar gastos específicos."""
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))  # ej: "Moto Honda", "Auto usado"
    kind: Mapped[str] = mapped_column(String(20))  # "moto" | "auto" | "otro"
    notes: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
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
    # Procedencia del ingreso (qué cliente o fuente pagó). Solo ingresos:
    # permite responder "¿cuánto entró de cada lado este mes?".
    source: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
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
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    target_cents: Mapped[int] = mapped_column(Integer)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Bill(Base):
    """Vencimiento: un pago futuro con fecha (tarjeta, alquiler, seguro...).

    El estado no se guarda: se deriva de `paid_at` y de `due_date` (ver
    `app.analytics.bill_rows`). Pagar un vencimiento genera el movimiento de
    gasto correspondiente; si es mensual, además crea el vencimiento siguiente.
    """

    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(Integer)  # centavos, nunca float
    due_date: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    recurrence: Mapped[str] = mapped_column(String(10), default="once")  # "once" | "monthly"
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    notes: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    category: Mapped[Category] = relationship()


class Budget(Base):
    """Presupuesto mensual de una categoría.

    El monto es por mes calendario y se aplica a todos los meses hasta que se
    cambie o se elimine. `category_id` es único: una categoría, un presupuesto.

    `rollover_cents` guarda lo que sobró (positivo) o faltó (negativo) del mes
    anterior y se suma al límite del mes actual para dar el "tope efectivo".
    """

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    rollover_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    category: Mapped[Category] = relationship()
