"""Utilidades compartidas por las herramientas del agente.

Acá viven las conversiones de moneda y los helpers de consulta que usan todos
los dominios (transacciones, objetivos, presupuestos).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import Category


# ---------------------------------------------------------------------------
# Conversión de moneda (evitar floats en la base de datos)
# ---------------------------------------------------------------------------

def money_to_cents(amount: float) -> int:
    return int((Decimal(str(amount)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def cents_to_money(cents: int) -> float:
    return cents / 100.0


def _fmt(cents: int, currency: str) -> str:
    """Formatea en convención argentina: 1.234.567,89 (punto miles, coma decimal).

    El texto que ve el modelo tiene que hablar el mismo idioma que el chat:
    el prompt del sistema le pide separador de miles con punto, así que la
    herramienta no puede devolverle "1,234,567.89" y esperar que lo traduzca.
    """
    entero, _, decimal = f"{cents / 100:,.2f}".partition(".")
    entero = entero.replace(",", ".")  # separador de miles
    return f"{entero},{decimal} {currency}"


def fmt(cents: int) -> str:
    return _fmt(cents, get_settings().currency)


def fmt_amount(amount: float | int | str) -> str:
    """Formatea un monto que viene de los argumentos del modelo.

    El modelo manda "150000" o "150000.5"; en la tarjeta de confirmación eso
    tiene que verse como $150.000,00, no como el número crudo que generó.
    """
    try:
        cents = money_to_cents(float(amount))
    except (TypeError, ValueError):
        return str(amount)  # si no es un número, se muestra tal cual
    return _fmt(cents, get_settings().currency)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"Fecha inválida: '{value}'. Usá el formato YYYY-MM-DD.")


def find_category(db: Session, user_id: int, name: str, kind: str | None = None) -> Category:
    """Busca una categoría DEL USUARIO por nombre (sin distinguir mayúsculas, con fuzzy match).

    Acepta coincidencia exacta, contenida (\"comida\" → \"Comida\"),
    o que el nombre de la categoría esté contenido en la query (\"supermercado\" → \"Comida\").
    """
    normalized = name.strip().lower()

    # 1. Exact match (case-insensitive)
    cat = db.scalar(
        select(Category).where(
            Category.user_id == user_id,
            func.lower(Category.name) == normalized,
        )
    )
    if cat:
        if kind and cat.kind != kind:
            raise ValueError(f"La categoría '{cat.name}' es de tipo '{cat.kind}', no de '{kind}'.")
        return cat

    # 2. Query contains category name (e.g. "presupuesto para comida" → "Comida")
    all_cats = db.scalars(select(Category).where(Category.user_id == user_id)).all()
    for c in all_cats:
        if c.name.lower() in normalized:
            if kind and c.kind != kind:
                continue
            return c

    # 3. Category name contains query (e.g. "comida" → "Comida")
    for c in all_cats:
        if normalized in c.name.lower():
            if kind and c.kind != kind:
                continue
            return c

    # Sin match: error con catálogo
    raise ValueError(
        f"No existe la categoría '{name}'. {category_catalogue(db, user_id)}"
    )


def category_catalogue(db: Session, user_id: int) -> str:
    rows = db.scalars(
        select(Category)
        .where(Category.user_id == user_id)
        .order_by(Category.kind, Category.name)
    ).all()
    income = ", ".join(c.name for c in rows if c.kind == "income") or "(ninguna)"
    expense = ", ".join(c.name for c in rows if c.kind == "expense") or "(ninguna)"
    return f"Categorías de ingreso: {income}. Categorías de gasto: {expense}."
