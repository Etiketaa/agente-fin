"""Punto de entrada: app FastAPI + estáticos + seed de categorías por usuario."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select

from .api import router
from .db import Base, SessionLocal, engine
from .models import User

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Columnas que el código da por existentes. `create_all()` crea las tablas que
# faltan pero NO agrega columnas a las que ya están: sin este chequeo, una base
# de una versión anterior rompería más adelante con un "no such column" dentro de
# una consulta, lejos de la causa real.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "users": {"id", "username", "password_hash", "created_at"},
    "user_sessions": {"id", "user_id", "token_hash", "created_at"},
    "categories": {"id", "user_id", "name", "kind", "created_at"},
    "vehicles": {"id", "user_id", "name", "kind", "notes", "created_at"},
    "transactions": {
        "id", "user_id", "type", "amount_cents", "description", "date", "category_id",
        "goal_id", "tags", "vehicle_id", "import_hash", "source", "created_at",
    },
    "savings_goals": {"id", "user_id", "name", "target_cents", "target_date", "kind", "notes", "created_at"},
    "budgets": {"id", "user_id", "category_id", "amount_cents", "rollover_cents", "created_at"},
    "bills": {
        "id", "user_id", "description", "amount_cents", "due_date", "category_id",
        "recurrence", "paid_at", "notes", "created_at",
    },
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

@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    Base.metadata.create_all(engine)
    # Ya no se siembran categorías globales: cada usuario recibe las suyas al
    # registrarse (ver app/seed.py). Los usuarios existentes sin categorías las
    # reciben en el primer request autenticado (get_current_user las completa).
    from .seed import DEFAULT_CATEGORIES, seed_user_categories

    db = SessionLocal()
    try:
        for user in db.scalars(select(User)).all():
            seed_user_categories(db, user)
    finally:
        db.close()
    yield


app = FastAPI(title="Finanzas Personales", lifespan=lifespan)


@app.get("/health")
def health():
    """Sonda mínima para verificar que el proceso responde."""
    return {"status": "ok"}


app.include_router(router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")