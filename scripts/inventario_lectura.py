"""Inventario de solo lectura de los usuarios y sus datos.

Uso:  .venv/bin/python -m scripts.inventario_lectura

No escribe NADA. Antes de la primera consulta fuerza la sesión de Postgres a
"read only" (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`): si el
servidor la acepta, cualquier intento de escribir después es rechazado por la
base, no por una promesa mía. Es la salvaguarda para poder correr esto contra la
base real sin riesgo.

Muestra, por usuario: movimientos, cuentas, vencimientos, presupuestos, metas,
categorías y sesiones. Sirve para decidir qué es dato de prueba y qué es real
antes de borrar nada.
"""
from __future__ import annotations

from sqlalchemy import func, select, text

from app.config import get_settings  # noqa: F401  (asegura .env cargado)
from app.db import SessionLocal, engine
from app.models import (
    Account,
    Bill,
    Budget,
    Category,
    SavingsGoal,
    Transaction,
    User,
    UserSession,
    Vehicle,
)

TABLAS = {
    "cuentas": Account,
    "categorias": Category,
    "movimientos": Transaction,
    "vencimientos": Bill,
    "presupuestos": Budget,
    "metas": SavingsGoal,
    "vehiculos": Vehicle,
    "sesiones": UserSession,
}


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"))
        print("sesion: SOLO LECTURA (Postgres rechaza cualquier escritura)\n")

        usuarios = db.scalars(select(User).order_by(User.id)).all()

        print(f"total de usuarios: {len(usuarios)}\n")
        encabezado = f"{'id':>4}  {'usuario':<16} {'creado':<11}"
        for nombre in TABLAS:
            encabezado += f" {nombre[:9]:>9}"
        print(encabezado)
        print("-" * len(encabezado))

        totales = {nombre: 0 for nombre in TABLAS}
        for u in usuarios:
            creado = u.created_at.strftime("%d/%m") if u.created_at else "?"
            fila = f"{u.id:>4}  {u.username:<16} {creado:<11}"
            for nombre, modelo in TABLAS.items():
                n = db.scalar(
                    select(func.count()).select_from(modelo).where(modelo.user_id == u.id)
                )
                totales[nombre] += n or 0
                fila += f" {n:>9}"
            print(fila)

        print("-" * len(encabezado))
        fila = f"{'':>4}  {'TOTALES':<16} {'':<11}"
        for nombre in TABLAS:
            fila += f" {totales[nombre]:>9}"
        print(fila)
    finally:
        db.close()


if __name__ == "__main__":
    main()
