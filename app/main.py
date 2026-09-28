"""Punto de entrada: app FastAPI + estáticos + seed de categorías."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select

from .api import router
from .db import Base, SessionLocal, engine
from .models import Category, Vehicle

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Columnas que el código da por existentes. `create_all()` crea las tablas que
# faltan pero NO agrega columnas a las que ya están: sin este chequeo, una base
# de una versión anterior rompería más adelante con un "no such column" dentro de
# una consulta, lejos de la causa real.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "categories": {"id", "name", "kind", "created_at"},
    "vehicles": {"id", "name", "kind", "notes", "created_at"},
    "transactions": {
        "id", "type", "amount_cents", "description", "date", "category_id",
        "goal_id", "tags", "vehicle_id", "import_hash", "created_at",
    },
    "savings_goals": {"id", "name", "target_cents", "target_date", "notes", "created_at"},
    "budgets": {"id", "category_id", "amount_cents", "rollover_cents", "created_at"},
}


def ensure_schema() -> None:
    """Falla al arrancar, y con un mensaje útil, si el esquema está desactualizado."""
    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())
    for tabla, esperadas in EXPECTED_COLUMNS.items():
        if tabla not in tablas:
            continue  # la va a crear create_all() justo después
        actuales = {c["name"] for c in inspector.get_columns(tabla)}
        faltantes = esperadas - actuales
        if faltantes:
            raise RuntimeError(
                f"El esquema de la tabla '{tabla}' está desactualizado: faltan las "
                f"columnas {sorted(faltantes)}.\n"
                f"Este proyecto no trae migraciones automáticas. Resolvedlo así:\n"
                f"  1. Si los datos no te importan: borrá finanzas.db y reiniciá el servidor.\n"
                f"  2. Si te importan: agregá la(s) columna(s) a mano antes de arrancar "
                f"(SQLite: ALTER TABLE {tabla} ADD COLUMN ...)."
            )

DEFAULT_CATEGORIES = [
    ("Sueldo", "income"),
    ("Freelance", "income"),
    ("Otros ingresos", "income"),
    ("Comida", "expense"),
    ("Transporte", "expense"),
    ("Vivienda", "expense"),
    ("Servicios", "expense"),
    ("Salud", "expense"),
    ("Educación", "expense"),
    ("Ocio", "expense"),
    ("Motos", "expense"),
    ("Compras", "expense"),
    ("Otros", "expense"),
]


def seed_categories() -> None:
    db = SessionLocal()
    try:
        existing = {name for (name,) in db.execute(select(Category.name)).all()}
        for name, kind in DEFAULT_CATEGORIES:
            if name not in existing:
                db.add(Category(name=name, kind=kind))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    Base.metadata.create_all(engine)
    seed_categories()
    yield


app = FastAPI(title="Finanzas Personales", lifespan=lifespan)


@app.get("/health")
def health():
    """Sonda mínima para verificar que el proceso responde."""
    return {"status": "ok"}


app.include_router(router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")