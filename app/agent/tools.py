"""
Herramientas del agente: definición (schema) + implementación.

Cada función recibe `db` y un dict de argumentos, y devuelve un
string legible que el modelo usa como resultado de la herramienta.
Los montos se guardan en centavos; las conversiones viven acá.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Category, Transaction


# ---------------------------------------------------------------------------
# Conversión de moneda (evitar floats en la base de datos)
# ---------------------------------------------------------------------------

def money_to_cents(amount: float) -> int:
    return int((Decimal(str(amount)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def cents_to_money(cents: int) -> float:
    return cents / 100.0


def _fmt(cents: int, currency: str) -> str:
    return f"{cents_to_money(cents):,.2f} {currency}"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value))


def _categories_available(db: Session) -> str:
    rows = db.scalars(select(Category).order_by(Category.kind, Category.name)).all()
    income = ", ".join(c.name for c in rows if c.kind == "income") or "(ninguna)"
    expense = ", ".join(c.name for c in rows if c.kind == "expense") or "(ninguna)"
    return f"Ingresos: {income} | Gastos: {expense}"


# ---------------------------------------------------------------------------
# Implementaciones de las herramientas
# ---------------------------------------------------------------------------

def listar_categorias(db: Session, args: dict) -> str:
    return _categories_available(db)


def registrar_transaccion(db: Session, args: dict) -> str:
    settings = get_settings()
    tipo = str(args.get("tipo", "")).lower()
    if tipo not in ("income", "expense"):
        raise ValueError("El campo 'tipo' debe ser 'income' (ingreso) o 'expense' (gasto).")
    monto = float(args.get("monto", 0))
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a cero.")
    cat_name = str(args.get("categoria", "")).strip()
    cat = db.scalar(select(Category).where(func.lower(Category.name) == func.lower(cat_name)))
    if cat is None:
        raise ValueError(f"No existe la categoría '{cat_name}'. Categorías disponibles: {_categories_available(db)}")
    if cat.kind != tipo:
        raise ValueError(f"La categoría '{cat.name}' es de {cat.kind}, no de {tipo}.")
    t = Transaction(
        type=tipo,
        amount_cents=money_to_cents(monto),
        category_id=cat.id,
        description=str(args.get("descripcion", "")).strip(),
        date=_parse_date(args.get("fecha")) or date.today(),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    desc = f" — {t.description}" if t.description else ""
    return (
        f"Transacción #{t.id} registrada: {_fmt(t.amount_cents, settings.currency)} "
        f"({tipo}) en {cat.name} el {t.date.isoformat()}{desc}."
    )


def listar_transacciones(db: Session, args: dict) -> str:
    settings = get_settings()
    q = select(Transaction).join(Category)
    tipo = args.get("tipo")
    if tipo:
        q = q.where(Transaction.type == str(tipo).lower())
    categoria = args.get("categoria")
    if categoria:
        q = q.where(func.lower(Category.name) == func.lower(str(categoria)))
    desde = _parse_date(args.get("desde"))
    if desde:
        q = q.where(Transaction.date >= desde)
    hasta = _parse_date(args.get("hasta"))
    if hasta:
        q = q.where(Transaction.date <= hasta)
    limite = min(int(args.get("limite", 20)), 50)
    rows = db.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limite)).all()
    if not rows:
        return "No hay transacciones con esos filtros."
    lines = [f"Transacciones ({len(rows)}):"]
    for t in rows:
        desc = f" — {t.description}" if t.description else ""
        lines.append(
            f"#{t.id} {t.date.isoformat()} [{t.type}] {t.category.name}: "
            f"{_fmt(t.amount_cents, settings.currency)}{desc}"
        )
    return "\n".join(lines)


def resumen_por_categoria(db: Session, args: dict) -> str:
    settings = get_settings()
    q = select(Transaction).join(Category)
    desde = _parse_date(args.get("desde"))
    if desde:
        q = q.where(Transaction.date >= desde)
    hasta = _parse_date(args.get("hasta"))
    if hasta:
        q = q.where(Transaction.date <= hasta)
    rows = db.scalars(q).all()
    if not rows:
        return "No hay transacciones en el período indicado."
    agrupado: dict[str, dict] = {}
    for t in rows:
        key = t.category.name
        item = agrupado.setdefault(key, {"kind": t.category.kind, "total_cents": 0})
        item["total_cents"] += t.amount_cents
    lines = ["Resumen por categoría:"]
    for name, item in sorted(agrupado.items(), key=lambda kv: -kv[1]["total_cents"]):
        lines.append(f"  {name} ({item['kind']}): {_fmt(item['total_cents'], settings.currency)}")
    return "\n".join(lines)


def calcular_balance(db: Session, args: dict) -> str:
    settings = get_settings()
    q = select(Transaction)
    desde = _parse_date(args.get("desde"))
    if desde:
        q = q.where(Transaction.date >= desde)
    hasta = _parse_date(args.get("hasta"))
    if hasta:
        q = q.where(Transaction.date <= hasta)
    rows = db.scalars(q).all()
    income = sum(t.amount_cents for t in rows if t.type == "income")
    expense = sum(t.amount_cents for t in rows if t.type == "expense")
    balance = income - expense
    periodo = []
    if desde:
        periodo.append(f"desde {desde.isoformat()}")
    if hasta:
        periodo.append(f"hasta {hasta.isoformat()}")
    sufijo = f" ({' '.join(periodo)})" if periodo else " (todo el historial)"
    return (
        f"Balance{sufijo}: {_fmt(balance, settings.currency)}. "
        f"Ingresos: {_fmt(income, settings.currency)}. "
        f"Gastos: {_fmt(expense, settings.currency)}."
    )


def eliminar_transaccion(db: Session, args: dict) -> str:
    tid = int(args.get("id", 0))
    t = db.get(Transaction, tid)
    if t is None:
        raise ValueError(f"No existe la transacción #{tid}.")
    db.delete(t)
    db.commit()
    return f"Transacción #{tid} eliminada."


# ---------------------------------------------------------------------------
# Registro de herramientas: schema (para el modelo) + implementación
# ---------------------------------------------------------------------------

_TOOL_IMPLS = {
    "listar_categorias": listar_categorias,
    "registrar_transaccion": registrar_transaccion,
    "listar_transacciones": listar_transacciones,
    "resumen_por_categoria": resumen_por_categoria,
    "calcular_balance": calcular_balance,
    "eliminar_transaccion": eliminar_transaccion,
}

TOOLS = [
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
            "description": "Registra un ingreso o gasto. Si el monto supera el umbral, el sistema pedirá confirmación al usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["income", "expense"], "description": "income = ingreso, expense = gasto"},
                    "monto": {"type": "number", "description": "Monto en la moneda local (ARS)"},
                    "categoria": {"type": "string", "description": "Nombre exacto de la categoría (usá listar_categorias si dudás)"},
                    "descripcion": {"type": "string", "description": "Descripción corta (opcional)"},
                    "fecha": {"type": "string", "description": "Fecha YYYY-MM-DD (opcional, por defecto hoy)"},
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


def execute_tool(name: str, args: dict, db: Session) -> str:
    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        raise ValueError(f"Herramienta desconocida: {name}")
    return impl(db, args)


# ---------------------------------------------------------------------------
# Acciones sensibles (requieren confirmación del usuario)
# ---------------------------------------------------------------------------

def is_sensitive(name: str, args: dict) -> bool:
    if name == "eliminar_transaccion":
        return True  # eliminar SIEMPRE requiere confirmación
    if name == "registrar_transaccion":
        return float(args.get("monto", 0)) >= get_settings().sensitive_amount
    return False


def summarize_action(name: str, args: dict) -> str:
    settings = get_settings()
    if name == "registrar_transaccion":
        tipo = "ingreso" if args.get("tipo") == "income" else "gasto"
        texto = f"Registrar {tipo} de {args.get('monto')} {settings.currency} en «{args.get('categoria')}»"
        if args.get("descripcion"):
            texto += f" — {args.get('descripcion')}"
        return texto
    if name == "eliminar_transaccion":
        return f"Eliminar la transacción #{args.get('id')}"
    return f"Ejecutar {name} con {args}"