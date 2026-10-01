"""Herramientas del agente: schemas (lo que ve el modelo) + implementaciones.

Cada dominio aporta su propio módulo (`transactions`, `goals`, `budgets`) con
las funciones y sus schemas; acá se arman los registros globales que consume
el bucle del agente.

La regla de seguridad vive en un solo lugar: `is_sensitive`. Toda herramienta
que escriba en la base tiene que pasar por ahí, y si devuelve True el bucle
frena la acción y pide confirmación en vez de ejecutarla.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...config import get_settings
from . import bills, budgets, goals, imports, transactions, vehicles
from .base import cents_to_money, fmt, fmt_amount, money_to_cents  # re-exportados

__all__ = [
    "TOOLS",
    "execute_tool",
    "is_sensitive",
    "summarize_action",
    "money_to_cents",
    "cents_to_money",
    "fmt",
    "fmt_amount",
]

# ---------------------------------------------------------------------------
# Registro de implementaciones
# ---------------------------------------------------------------------------

_IMPLS: dict[str, object] = {}
for _module in (transactions, goals, budgets, vehicles, imports, bills):
    _IMPLS.update(_module.IMPLS)

# ---------------------------------------------------------------------------
# Schemas que ve el modelo
#
# Orden: primero las de lectura (el modelo suele arrancar por acá para
# entender el estado), después las de escritura.
# ---------------------------------------------------------------------------

TOOLS = [
    *transactions.SCHEMAS,
    *goals.SCHEMAS,
    *budgets.SCHEMAS,
    *vehicles.SCHEMAS,
    *imports.SCHEMAS,
    *bills.SCHEMAS,
]

# Toda herramienta destructiva pasa por acá, sin excepción.
_SIEMPRE_SENSIBLE = {
    "eliminar_transaccion",
    "eliminar_objetivo",
    "eliminar_presupuesto",
    "eliminar_vehiculo",
    "importar_csv",  # escribe muchos registros de una
    "pagar_vencimiento",  # genera un gasto real + cambia estado
    "eliminar_vencimiento",
}

# Escrituras que se frenan a partir de cierto monto.
_SENSIBLE_POR_MONTO = {
    "registrar_transaccion": "monto",
}


def execute_tool(name: str, args: dict, db: Session, user_id: int) -> str:
    impl = _IMPLS.get(name)
    if impl is None:
        raise ValueError(f"Herramienta desconocida: {name}")
    return impl(db, args, user_id)  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Acciones sensibles (requieren confirmación del usuario)
# ---------------------------------------------------------------------------

def is_sensitive(name: str, args: dict) -> bool:
    if name in _SIEMPRE_SENSIBLE:
        return True
    monto_key = _SENSIBLE_POR_MONTO.get(name)
    if monto_key:
        try:
            return float(args.get(monto_key, 0)) >= get_settings().sensitive_amount
        except (TypeError, ValueError):
            return True  # monto ilegible: mejor frenar y preguntar
    return False


def summarize_action(name: str, args: dict) -> str:
    """Texto que el usuario lee antes de aprobar: tiene que ser claro y exacto."""

    if name == "registrar_transaccion":
        tipo = "ingreso" if args.get("tipo") == "income" else "gasto"
        texto = f"Registrar {tipo} de {fmt_amount(args.get('monto'))} en «{args.get('categoria')}»"
        if args.get("fuente"):
            texto += f" de {args['fuente']}"
        if args.get("objetivo"):
            texto += f" (al objetivo «{args['objetivo']}»)"
        if args.get("descripcion"):
            texto += f" — {args['descripcion']}"
        return texto

    if name == "eliminar_transaccion":
        return f"Eliminar la transacción #{args.get('id')}"

    if name == "crear_objetivo":
        tipo = "recaudación" if str(args.get("tipo", "")).lower() == "recaudacion" else "objetivo de ahorro"
        texto = (
            f"Crear la {tipo} «{args.get('nombre')}» "
            f"por {fmt_amount(args.get('monto'))}"
        )
        if args.get("fecha_limite"):
            texto += f", con fecha límite {args['fecha_limite']}"
        return texto

    if name == "eliminar_objetivo":
        return f"Eliminar el objetivo de ahorro #{args.get('id')}"

    if name == "definir_presupuesto":
        return (
            f"Definir un presupuesto mensual de {fmt_amount(args.get('monto'))} "
            f"para «{args.get('categoria')}»"
        )

    if name == "eliminar_presupuesto":
        return f"Eliminar el presupuesto #{args.get('id')}"

    if name == "crear_vehiculo":
        return f"Crear el vehículo «{args.get('nombre')}» (tipo: {args.get('tipo')})"

    if name == "eliminar_vehiculo":
        return f"Eliminar el vehículo #{args.get('id')}"

    if name == "importar_csv":
        return f"Importar movimientos desde «{args.get('archivo')}»"

    if name == "crear_vencimiento":
        texto = (
            f"Crear el vencimiento «{args.get('descripcion')}» por "
            f"{fmt_amount(args.get('monto'))} para el {args.get('fecha')}"
        )
        if str(args.get("recurrencia", "once")).lower() == "monthly":
            texto += " (mensual)"
        return texto

    if name == "pagar_vencimiento":
        return f"Pagar el vencimiento #{args.get('id')} (genera el gasto correspondiente)"

    if name == "eliminar_vencimiento":
        return f"Eliminar el vencimiento #{args.get('id')}"

    return f"Ejecutar {name} con {args}"
