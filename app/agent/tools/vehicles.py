"""Herramientas de vehículos (para gastos de moto/auto)."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Vehicle
from .base import fmt, find_category, money_to_cents


def _vehicle_line(v: Vehicle) -> str:
    return f"  - #{v.id} {v.name} ({v.kind})" + (f" — {v.notes}" if v.notes else "")


def listar_vehiculos(db: Session, args: dict) -> str:
    vehiculos = db.scalars(select(Vehicle).order_by(Vehicle.id)).all()
    if not vehiculos:
        return "No hay vehículos cargados. Podés crear uno con «creá un vehículo llamado Moto Honda tipo moto»."
    lines = ["Vehículos:"]
    lines.extend(_vehicle_line(v) for v in vehiculos)
    return "\n".join(lines)


def crear_vehiculo(db: Session, args: dict) -> str:
    name = str(args.get("nombre", "")).strip()
    kind = str(args.get("tipo", "")).strip().lower()  # moto | auto | otro
    notes = str(args.get("notas", "")).strip()

    if not name:
        raise ValueError("El nombre del vehículo no puede estar vacío.")
    if kind not in ("moto", "auto", "otro"):
        raise ValueError("Tipo debe ser: moto, auto u otro.")

    existing = db.scalar(select(Vehicle).where(Vehicle.name == name))
    if existing:
        raise ValueError(f"Ya existe un vehículo llamado '{name}'.")

    v = Vehicle(name=name, kind=kind, notes=notes)
    db.add(v)
    db.commit()
    db.refresh(v)
    return f"Vehículo «{v.name}» ({v.kind}) creado (#{v.id})."


def eliminar_vehiculo(db: Session, args: dict) -> str:
    vid = int(args.get("id", 0))
    v = db.get(Vehicle, vid)
    if v is None:
        raise ValueError(f"No existe el vehículo #{vid}.")
    name = v.name
    db.delete(v)
    db.commit()
    return f"Vehículo «{name}» eliminado."


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "listar_vehiculos",
            "description": "Lista los vehículos registrados (para asignar gastos de moto/auto).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crear_vehiculo",
            "description": "Registra un vehículo (moto/auto/otro) para poder etiquetar gastos como combustible, mantenimiento, seguro, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre del vehículo (ej: 'Moto Honda', 'Auto usado')"},
                    "tipo": {"type": "string", "description": "Tipo: 'moto', 'auto' u 'otro'"},
                    "notas": {"type": "string", "description": "Notas opcionales"},
                },
                "required": ["nombre", "tipo"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_vehiculo",
            "description": "Elimina un vehículo. Requiere confirmación.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID del vehículo"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
]

IMPLS = {
    "listar_vehiculos": listar_vehiculos,
    "crear_vehiculo": crear_vehiculo,
    "eliminar_vehiculo": eliminar_vehiculo,
}