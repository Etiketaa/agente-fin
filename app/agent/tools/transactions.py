"""Herramientas de movimientos: ingresos, gastos, categorías y balance."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Category, SavingsGoal, Transaction
from ...config import get_settings
from .base import (
    category_catalogue,
    find_category,
    fmt,
    money_to_cents,
    parse_date,
)


def listar_categorias(db: Session, args: dict, user_id: int) -> str:
    return category_catalogue(db, user_id)


def _owned_tx(db: Session, user_id: int, tid: int) -> Transaction:
    t = db.get(Transaction, tid)
    if t is None or t.user_id != user_id:
        raise ValueError(f"No existe la transacción #{tid}.")
    return t


def registrar_transaccion(db: Session, args: dict, user_id: int) -> str:
    tipo = str(args.get("tipo", "")).lower()
    if tipo not in ("income", "expense"):
        raise ValueError("El campo 'tipo' debe ser 'income' (ingreso) o 'expense' (gasto).")
    monto = float(args.get("monto", 0))
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a cero.")
    cat = find_category(db, user_id, str(args.get("categoria", "")), tipo)

    goal = None
    objetivo = str(args.get("objetivo", "")).strip()
    if objetivo:
        goal = db.scalar(
            select(SavingsGoal).where(
                SavingsGoal.user_id == user_id, SavingsGoal.name.ilike(objetivo)
            )
        )
        if goal is None:
            nombres = ", ".join(
                g.name
                for g in db.scalars(
                    select(SavingsGoal)
                    .where(SavingsGoal.user_id == user_id)
                    .order_by(SavingsGoal.name)
                ).all()
            )
            raise ValueError(
                f"No existe el objetivo '{objetivo}'. "
                f"Objetivos disponibles: {nombres or '(ninguno)'}."
            )

    # La procedencia solo aplica a ingresos (quién pagó / de dónde vino).
    fuente = str(args.get("fuente", "")).strip() or None
    if tipo != "income":
        fuente = None

    t = Transaction(
        user_id=user_id,
        type=tipo,
        amount_cents=money_to_cents(monto),
        category_id=cat.id,
        goal_id=goal.id if goal else None,
        description=str(args.get("descripcion", "")).strip(),
        date=parse_date(args.get("fecha")) or date.today(),
        source=fuente,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    desc = f" — {t.description}" if t.description else ""
    destino = f" asignado al objetivo «{goal.name}»" if goal else ""
    origen = f" (de {fuente})" if fuente else ""
    return (
        f"Transacción #{t.id} registrada: {fmt(t.amount_cents)} "
        f"({tipo}) en {cat.name} el {t.date.isoformat()}{desc}{destino}{origen}."
    )


def listar_transacciones(db: Session, args: dict, user_id: int) -> str:
    q = (
        select(Transaction)
        .join(Category)
        .where(Transaction.user_id == user_id, Category.user_id == user_id)
    )
    tipo = args.get("tipo")
    if tipo:
        q = q.where(Transaction.type == str(tipo).lower())
    categoria = args.get("categoria")
    if categoria:
        q = q.where(Category.name.ilike(str(categoria).strip()))
    objetivo = str(args.get("objetivo", "")).strip()
    if objetivo:
        goal = db.scalar(
            select(SavingsGoal).where(
                SavingsGoal.user_id == user_id, SavingsGoal.name.ilike(objetivo)
            )
        )
        if goal is None:
            raise ValueError(f"No existe el objetivo '{objetivo}'.")
        q = q.where(Transaction.goal_id == goal.id)
    desde = parse_date(args.get("desde"))
    if desde:
        q = q.where(Transaction.date >= desde)
    hasta = parse_date(args.get("hasta"))
    if hasta:
        q = q.where(Transaction.date <= hasta)
    limite = max(1, min(int(args.get("limite", 20)), 50))
    rows = db.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limite)).all()
    if not rows:
        return "No hay transacciones con esos filtros."
    lines = [f"Transacciones ({len(rows)}):"]
    for t in rows:
        desc = f" — {t.description}" if t.description else ""
        meta = f" [objetivo: {t.goal.name}]" if t.goal else ""
        lines.append(
            f"#{t.id} {t.date.isoformat()} [{t.type}] {t.category.name}: "
            f"{fmt(t.amount_cents)}{meta}{desc}"
        )
    return "\n".join(lines)


def resumen_por_categoria(db: Session, args: dict, user_id: int) -> str:
    q = (
        select(Transaction)
        .join(Category)
        .where(Transaction.user_id == user_id, Category.user_id == user_id)
    )
    desde = parse_date(args.get("desde"))
    if desde:
        q = q.where(Transaction.date >= desde)
    hasta = parse_date(args.get("hasta"))
    if hasta:
        q = q.where(Transaction.date <= hasta)
    rows = db.scalars(q).all()
    if not rows:
        return "No hay transacciones en el período indicado."
    agrupado: dict[str, dict] = {}
    for t in rows:
        item = agrupado.setdefault(t.category.name, {"kind": t.category.kind, "total_cents": 0})
        item["total_cents"] += t.amount_cents
    lines = ["Resumen por categoría:"]
    for name, item in sorted(agrupado.items(), key=lambda kv: -kv[1]["total_cents"]):
        lines.append(f"  {name} ({item['kind']}): {fmt(item['total_cents'])}")
    return "\n".join(lines)


def calcular_balance(db: Session, args: dict, user_id: int) -> str:
    q = select(Transaction).where(Transaction.user_id == user_id)
    desde = parse_date(args.get("desde"))
    if desde:
        q = q.where(Transaction.date >= desde)
    hasta = parse_date(args.get("hasta"))
    if hasta:
        q = q.where(Transaction.date <= hasta)
    rows = db.scalars(q).all()
    income = sum(t.amount_cents for t in rows if t.type == "income")
    expense = sum(t.amount_cents for t in rows if t.type == "expense")
    periodo = []
    if desde:
        periodo.append(f"desde {desde.isoformat()}")
    if hasta:
        periodo.append(f"hasta {hasta.isoformat()}")
    sufijo = f" ({' '.join(periodo)})" if periodo else " (todo el historial)"
    return (
        f"Balance{sufijo}: {fmt(income - expense)}. "
        f"Ingresos: {fmt(income)}. Gastos: {fmt(expense)}."
    )


def eliminar_transaccion(db: Session, args: dict, user_id: int) -> str:
    tid = int(args.get("id", 0))
    t = _owned_tx(db, user_id, tid)
    db.delete(t)
    db.commit()
    return f"Transacción #{tid} eliminada."


# ---------------------------------------------------------------------------
# Schemas para el modelo
# ---------------------------------------------------------------------------

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "listar_transacciones",
            "description": "Lista transacciones (ingresos y gastos) con filtros opcionales.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["income", "expense"], "description": "Filtrar por tipo"},
                    "categoria": {"type": "string", "description": "Nombre exacto de la categoría"},
                    "objetivo": {"type": "string", "description": "Solo movimientos asignados a este objetivo de ahorro"},
                    "desde": {"type": "string", "description": "Fecha inicial YYYY-MM-DD"},
                    "hasta": {"type": "string", "description": "Fecha final YYYY-MM-DD"},
                    "limite": {"type": "integer", "description": "Cantidad máxima de resultados (default 20)"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_balance",
            "description": "Calcula el balance (ingresos - gastos) en un período opcional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "desde": {"type": "string", "description": "Fecha inicial YYYY-MM-DD"},
                    "hasta": {"type": "string", "description": "Fecha final YYYY-MM-DD"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resumen_por_categoria",
            "description": "Resumen de gastos e ingresos agrupados por categoría.",
            "parameters": {
                "type": "object",
                "properties": {
                    "desde": {"type": "string", "description": "Fecha inicial YYYY-MM-DD"},
                    "hasta": {"type": "string", "description": "Fecha final YYYY-MM-DD"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_categorias",
            "description": "Lista las categorías de ingresos y gastos disponibles.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_transaccion",
            "description": (
                "Registra un ingreso o gasto. Usá 'objetivo' para separar dinero "
                "para un objetivo de ahorro (el movimiento suma a su progreso). "
                "Si el monto supera el umbral, el sistema pedirá confirmación al usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["income", "expense"], "description": "income = ingreso, expense = gasto"},
                    "monto": {"type": "number", "description": "Monto en la moneda local (ARS)"},
                    "categoria": {"type": "string", "description": "Nombre exacto de la categoría (usá listar_categorias si dudás)"},
                    "descripcion": {"type": "string", "description": "Descripción corta (opcional)"},
                    "fecha": {"type": "string", "description": "Fecha YYYY-MM-DD (opcional, por defecto hoy)"},
                    "objetivo": {"type": "string", "description": "Nombre exacto del objetivo de ahorro al que se asigna (opcional). Si es una recaudación: los ingresos asignados suman a la bolsa y los gastos restan."},
                    "fuente": {"type": "string", "description": "Procedencia del ingreso: quién pagó (cliente, empresa). Solo para tipo=income."},
                },
                "required": ["tipo", "monto", "categoria"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_transaccion",
            "description": "Elimina una transacción existente. Esta acción es sensible y requiere confirmación del usuario.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID de la transacción a eliminar"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
]

IMPLS = {
    "listar_categorias": listar_categorias,
    "registrar_transaccion": registrar_transaccion,
    "listar_transacciones": listar_transacciones,
    "resumen_por_categoria": resumen_por_categoria,
    "calcular_balance": calcular_balance,
    "eliminar_transaccion": eliminar_transaccion,
}
