"""Punto de entrada: app FastAPI + estáticos + seed de categorías por usuario."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select

from .api import router
from .config import db_fingerprint, get_settings
from .db import Base, SessionLocal, engine
from .migrations import run_migrations
from .models import User

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Columnas que el código da por existentes. `create_all()` crea las tablas que
# faltan pero NO agrega columnas a las que ya están: sin este chequeo, una base
# de una versión anterior rompería más adelante con un "no such column" dentro de
# una consulta, lejos de la causa real.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "users": {"id", "username", "password_hash", "created_at"},
    "user_sessions": {"id", "user_id", "token_hash", "created_at", "expires_at"},
    "categories": {"id", "user_id", "name", "kind", "created_at"},
    "vehicles": {"id", "user_id", "name", "kind", "notes", "created_at"},
    "transactions": {
        "id", "user_id", "type", "amount_cents", "description", "date", "category_id",
        "goal_id", "tags", "vehicle_id", "import_hash", "source", "cuenta_id", "created_at",
    },
    "savings_goals": {"id", "user_id", "name", "target_cents", "target_date", "kind", "notes", "created_at"},
    "budgets": {"id", "user_id", "category_id", "amount_cents", "rollover_cents", "created_at"},
    "bills": {
        "id", "user_id", "description", "amount_cents", "due_date", "category_id",
        "recurrence", "paid_at", "notes", "created_at",
    },
    "accounts": {
        "id", "user_id", "name", "kind", "apertura_cents", "notes", "created_at",
        "updated_at",
    },
    "login_attempts": {"clave", "intentos", "ultima_prueba"},
}


def ensure_schema() -> None:
    """Falla al arrancar, y con un mensaje útil, si el esquema está desactualizado.

    Es la red de seguridad de `app/migrations.py`, no el mecanismo: las columnas
    que agrega una migración ya deberían estar cuando corre esto. Si se dispara,
    significa que hay una columna nueva en el código que ninguna migración crea,
    y eso hay que arreglarlo en el código, no a mano en la base.
    """
    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())
    for tabla, esperadas in EXPECTED_COLUMNS.items():
        if tabla not in tablas:
            # `create_all()` ya corrió antes que este chequeo, así que una tabla
            # que no está acá no es "una tabla que falta": es una entrada de este
            # diccionario que quedó vieja, porque el modelo ya no existe en
            # app/models.py. Se pasa de largo, porque una expectativa obsoleta no
            # debería frenar el arranque. Lo que sí frena es una COLUMNA que
            # falte, y esa es la razón de ser de este chequeo.
            continue
        actuales = {c["name"] for c in inspector.get_columns(tabla)}
        faltantes = esperadas - actuales
        if faltantes:
            raise RuntimeError(
                f"El esquema de la tabla '{tabla}' está desactualizado: faltan las "
                f"columnas {sorted(faltantes)}.\n"
                f"La app aplica migraciones al arrancar (ver app/migrations.py), así "
                f"que esto significa que esa columna no está en ninguna migración y "
                f"hay que agregarla:\n"
                f"  - Escribí la migración en app/migrations.py y sumala a MIGRACIONES.\n"
                f"  - Para una base de prueba: borrá finanzas.db y reiniciá el servidor."
            )

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # El orden importa y es de menos a más caro de romper:
    #   1. `create_all` crea las tablas que faltan.
    #   2. `run_migrations` agrega las columnas que faltan (y anota qué aplicó).
    #   3. `ensure_schema` verifica que el esquema esté completo.
    # Así una base vieja sube sola y la red de seguridad sigue estando, pero como
    # última línea y no como el único mecanismo: avisar que falta una columna no
    # es lo mismo que agregarla.
    Base.metadata.create_all(engine)
    aplicadas = run_migrations(engine)
    if aplicadas:
        print("migraciones aplicadas: " + "; ".join(aplicadas))
    ensure_schema()
    # Ya no se siembran categorías globales: cada usuario recibe las suyas al
    # registrarse (ver app/seed.py). Los usuarios existentes sin categorías las
    # reciben en el primer request autenticado (get_current_user las completa).
    from .seed import DEFAULT_CATEGORIES, seed_user_accounts, seed_user_categories

    db = SessionLocal()
    try:
        for user in db.scalars(select(User)).all():
            seed_user_categories(db, user)
            # Billetera «General» + imputación de movimientos sin cuenta
            # (idempotente: sólo toca los que no la tienen).
            seed_user_accounts(db, user)
    finally:
        db.close()
    yield


app = FastAPI(title="Finanzas Personales", lifespan=lifespan)


@app.get("/health")
def health():
    """Sonda mínima para verificar que el proceso responde.

    Devuelve también la huella de la base: es pública, no lleva credenciales, y le
    permite a un test confirmar que está hablando con la base que cree antes de
    escribir en ella (ver `app.config.db_fingerprint`).
    """
    return {"status": "ok", "db": db_fingerprint(get_settings().database_url)}


app.include_router(router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")