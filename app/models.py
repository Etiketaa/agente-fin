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
    # De qué billetera salió/entró la plata. Opcional en el formulario, pero el
    # backend siempre lo resuelve (a "General" si no viene), así ningún
    # movimiento queda fuera del patrimonio. Es lo que mantiene al día el saldo
    # de cada billetera (ver `models.Account`).
    cuenta_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    category: Mapped[Category] = relationship()
    goal: Mapped["SavingsGoal | None"] = relationship()
    vehicle: Mapped["Vehicle | None"] = relationship()
    account: Mapped["Account | None"] = relationship()


class Account(Base):
    """Billetera o cuenta donde tenés la plata: Mercado Pago, banco, efectivo.

    Con varias billeteras (y más todavía si las van a usar clientes) el saldo
    NO puede ser un número que el usuario escribe y se queda viejo: serían N
    actualizaciones manuales por semana y en dos semanas el total miente.

    Entonces el saldo es derivado, como en una agenda de cuentas real:

        saldo = apertura_cents + Σ movimientos de esta billetera

    - `apertura_cents` es el saldo real que tenía el día que la cargaste. Se
      escribe una vez, y es la verdad de partida contra la app.
    - Cada movimiento con `cuenta_id` apunta a una billetera: los cobros suman,
      los gastos restan. El saldo se mantiene solo.
    - Si la realidad se desvía (un movimiento que no cargaste, un cobro que
      no entró), "Ajustar saldo" recalcula la apertura para que el saldo
      derive exactamente al número real. No borra historia ni inventa
      movimientos.

    Un movimiento sin `cuenta_id` nunca queda huérfano: el backend lo imputa a
    la billetera "General" del usuario, así el patrimonio total nunca pierde
    plata (ver `app.seed.DEFAULT_ACCOUNT_NAME`).
    """

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))  # "Mercado Pago", "Banco", "Efectivo"
    kind: Mapped[str] = mapped_column(String(10), default="otro")  # banco|digital|efectivo|otro
    apertura_cents: Mapped[int] = mapped_column(Integer, default=0)  # saldo de partida
    notes: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SavingsGoal(Base):
    """Objetivo de ahorro: una meta con monto a juntar y fecha opcional.

    No tiene columna de "saldo": el progreso se deriva de los movimientos con
    `goal_id`. Un único libro contable, sin contador que pueda desincronizarse.

    `kind` cambia cómo se calcula el progreso:
    - ahorro: suma de TODOS los movimientos asignados (cada aporte suma).
    - recaudacion: ingresos − gastos asignados (plata que entró menos lo que
      ya se usó de esa bolsa). El dinero recaudado tiene un destino trazable.
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
    kind: Mapped[str] = mapped_column(String(15), default="ahorro")  # ahorro | recaudacion
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
