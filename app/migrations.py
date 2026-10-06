"""Migraciones de esquema: versionadas, idempotentes y aplicadas al arrancar.

Por qué existe esto
-------------------
`Base.metadata.create_all()` crea las tablas que faltan pero NO agrega columnas
a las que ya existen. Sin este módulo, la primera columna nueva obligaba a
correr `ALTER TABLE` a mano contra la base real: si se olvidaba, la app no
levantaba en producción y el error aparecía lejos de la causa. `ensure_schema()`
en `app/main.py` detectaba el desfase, pero avisar no es migrar.

Cómo funciona
-------------
Una lista ordenada de pasos, cada uno con un id. Al arrancar se aplica solo el
que falte y se anota en la tabla `schema_migrations`. Cada paso se escribe para
poder correr dos veces sin romper: la segunda vez detecta que ya está y no hace
nada. Así el mismo camino sirve para una base nueva (donde no hay nada que
migrar) y para una base con datos (donde hay que agregar la columna).

Cómo agregar una migración
--------------------------
1. Escribir la función abajo (un `_00N_descripcion(engine)` que devuelva una
   frase con lo que hizo).
2. Agregarla a la lista `MIGRACIONES`. El orden de la lista es el orden de
   aplicación: no se reordena lo que ya corrió en otras bases.
3. Si el paso agrega una columna,(sumala también a `EXPECTED_COLUMNS` en
   `app/main.py` para que la red de seguridad la conozca.

Sin dependencias nuevas: solo SQLAlchemy y `text()`.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine

from .db import SessionLocal
from .models import UserSession

# Identificador de la tabla donde queda registrado qué corrió. Se crea acá y no
# en `models.py` a propósito: es bookkeeping de la infraestructura, no dominio,
# y no tiene por qué viajar con los modelos de datos.
_REGISTRO = "schema_migrations"


def _asegurar_registro(engine: Engine) -> None:
    """Crea la tabla de registro si no existe. Idempotente por construcción."""
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_REGISTRO} ("
            "  id VARCHAR(64) PRIMARY KEY,"
            "  aplicada_en TIMESTAMP NOT NULL"
            ")"
        ))


def _aplicadas(engine: Engine) -> set[str]:
    with engine.begin() as conn:
        filas = conn.execute(text(f"SELECT id FROM {_REGISTRO}")).fetchall()
    return {f[0] for f in filas}


def _anotar(engine: Engine, id_migracion: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {_REGISTRO} (id, aplicada_en) VALUES (:id, :fecha)"),
            {"id": id_migracion, "fecha": datetime.now()},
        )


def _agregar_columna(engine: Engine, tabla: str, columna: str, tipo_sql: str) -> bool:
    """Agrega una columna si la tabla existe y la columna todavía no.

    `ALTER TABLE ... ADD COLUMN` no es idempotente en Postgres (falla si la
    columna ya está), así que el chequeo va antes, con el inspector: por eso
    llamar dos veces a esta función es seguro.

    Los nombres de tabla y columna son literales del código, nunca vienen de un
    pedido del cliente: por eso se pueden interpolar en el SQL.
    """
    inspector = inspect(engine)
    if tabla not in inspector.get_table_names():
        return False  # la tabla no existe todavía; `create_all` se encarga
    if any(c["name"] == columna for c in inspector.get_columns(tabla)):
        return False  # ya está
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sql}"))
    return True


def _001_sesiones_expiran(engine: Engine) -> str:
    """Las sesiones tienen fecha de vencimiento.

    Antes esta tabla no tenía vencimiento: un token robado daba acceso a la
    plata para siempre, y logout era la única salida.

    Las sesiones que ya existen NO se invalidan: se les calcula el vencimiento
    desde su propia `created_at`, así la sesión del celu sigue viva y las viejas
    mueren solas cuando les toque.
    """
    from .config import get_settings

    if not _agregar_columna(engine, "user_sessions", "expires_at", "TIMESTAMP"):
        return "la columna ya estaba"

    ttl = timedelta(days=get_settings().session_ttl_days)
    db = SessionLocal()
    try:
        pendientes = db.scalars(
            select(UserSession).where(UserSession.expires_at.is_(None))
        ).all()
        for s in pendientes:
            s.expires_at = (s.created_at or datetime.now()) + ttl
        db.commit()
    finally:
        db.close()
    return f"columna agregada, {len(pendientes)} sesiones con vencimiento"


# El orden de la lista es el orden de aplicación. No reordenar lo que ya corrió
# en otras bases: la numeración es la que garantiza que un `001` faltante se
# aplique antes que un `002`.
MIGRACIONES: tuple[tuple[str, Callable[[Engine], str]], ...] = (
    ("001_sesiones_expiran", _001_sesiones_expiran),
)


def run_migrations(engine: Engine) -> list[str]:
    """Aplica las migraciones pendientes. Devuelve un log de lo que hizo.

    Cada migración va en su propia transacción junto con la anotación: si el
    paso falla, no queda a medias ni registrado como aplicado, y el próximo
    arranque lo reintenta.
    """
    _asegurar_registro(engine)
    ya = _aplicadas(engine)
    log: list[str] = []
    for id_migracion, paso in MIGRACIONES:
        if id_migracion in ya:
            continue
        detalle = paso(engine)
        _anotar(engine, id_migracion)
        log.append(f"{id_migracion}: {detalle}")
    return log
