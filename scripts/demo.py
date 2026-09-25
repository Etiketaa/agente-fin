"""Carga datos de ejemplo (opcional) para ver la app con contenido.

Uso:  python -m scripts.demo
Para empezar de cero: borrá finanzas.db y reiniciá el servidor.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.config import get_settings, BASE_DIR  # noqa: F401  (asegura .env cargado)
from app.db import Base, SessionLocal, engine
from app.agent.tools import money_to_cents
from app.models import Category, Transaction

DEFAULT_CATEGORIES = [
    ("Sueldo", "income"), ("Freelance", "income"), ("Otros ingresos", "income"),
    ("Comida", "expense"), ("Transporte", "expense"), ("Vivienda", "expense"),
    ("Servicios", "expense"), ("Salud", "expense"), ("Educación", "expense"),
    ("Ocio", "expense"), ("Motos", "expense"), ("Compras", "expense"), ("Otros", "expense"),
]


def main() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        existing = {name for (name,) in db.execute(select(Category.name)).all()}
        for name, kind in DEFAULT_CATEGORIES:
            if name not in existing:
                db.add(Category(name=name, kind=kind))
        db.commit()
        cats = {c.name: c for c in db.scalars(select(Category)).all()}
        today = date.today()
        first = today.replace(day=1)
        samples = [
            ("income", 850000, "Sueldo", "Sueldo mensual", first - timedelta(days=2)),
            ("expense", 125000, "Vivienda", "Alquiler", first + timedelta(days=5)),
            ("expense", 35000, "Comida", "Supermercado", first + timedelta(days=6)),
            ("expense", 48000, "Motos", "Cubiertas + service", first + timedelta(days=8)),
            ("expense", 15000, "Motos", "Combustible", first + timedelta(days=10)),
            ("expense", 9000, "Transporte", "Nafta / sube", first + timedelta(days=12)),
            ("expense", 22000, "Servicios", "Luz + internet", first + timedelta(days=14)),
            ("income", 120000, "Freelance", "Proyecto web", first + timedelta(days=15)),
            ("expense", 8000, "Ocio", "Salida", first + timedelta(days=18)),
            ("expense", 6000, "Salud", "Farmacia", first + timedelta(days=20)),
        ]
        db.add_all(
            [
                Transaction(type=t, amount_cents=money_to_cents(m), category_id=cats[c].id,
                            description=d, date=f)
                for t, m, c, d, f in samples
            ]
        )
        db.commit()
        print("Datos de ejemplo cargados.")
    finally:
        db.close()


if __name__ == "__main__":
    main()