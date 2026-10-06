"""Borrado de los usuarios de prueba de la base real, con guarda explícita.

Uso:
    .venv/bin/python -m scripts.limpiar_usuarios_prueba            # dry-run: solo informa
    .venv/bin/python -m scripts.limpiar_usuarios_prueba --yes      # borra de verdad

Sin `--yes` NO borra: imprime el plan exacto (qué usuarios, cuántas filas de cada
tabla) y termina. La ejecución real exige el flag, así la escritura nunca ocurre
por accidente ni por un `Enter` apurado.

La lista de usuarios es una lista blanca explícita, no un patrón: se decide
usuario por usuario, no "todo lo que parezca de prueba". Un usuario que no esté
en la lista nunca se toca, aunque su nombre huela a smoke test. Y `PROTEGIDOS`
es una lista de nombres que el script se niega a borrar aunque estén en la
lista blanca: es una segunda comprobación independiente, para que un error de
copia y pega en la lista no borre tu cuenta.

El borrado va en una sola transacción: si algo falla, no queda nada a medias.
"""
from __future__ import annotations

import sys

from sqlalchemy import delete, func, select, text

from app.config import get_settings  # noqa: F401  (asegura .env cargado)
from app.db import SessionLocal
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

# Usuarios de prueba que se borran. Verificados contra la base real: ninguno
# tiene movimientos reales, son de corridas de smoke y pruebas de navegador.
USUARIOS_A_BORRAR = [
    "__probe__",
    "probe1791148817",
    "a1791148862",
    "b1791148862",
    "c1791149104",
    "ux149184",
    "smoke_a",
    "smoke_b",
    "dbg150183",
    "dbg150460",
    "rg151176",
    "cx200277",
    "ag201096",
    "fase1",
    "casob",
    "casoc",
    "fase2",
    # Los tres siguientes los vuelve a crear el smoke (`smoke_a`, `smoke_b`) o
    # `scripts/demo.py` (`demo`). `demo` además es una cuenta ABIERTA: su
    # contraseña es la constante `DEMO_PASSWORD = "demo1234"` del repo, así que
    # cualquiera que conozca la URL puede entrar a la base real.
    "demo",
]

# Nombres que el script se niega a borrar, aunque estén en la lista de arriba.
PROTEGIDOS = {"franc"}

# Orden de borrado: primero las filas que apuntan al usuario, al final el
# usuario. Evita depender del CASCADE para las referencias internas
# (una categoría apunta a su usuario y a la vez la apuntan los movimientos).
ORDEN = [
    ("sesiones", UserSession),
    ("movimientos", Transaction),
    ("vencimientos", Bill),
    ("presupuestos", Budget),
    ("metas", SavingsGoal),
    ("cuentas", Account),
    ("categorias", Category),
    ("vehiculos", Vehicle),
]


def main() -> int:
    ejecutar = "--yes" in sys.argv

    db = SessionLocal()
    try:
        users = db.scalars(select(User).order_by(User.id)).all()
        por_nombre = {u.username: u for u in users}

        objetivo = [por_nombre[n] for n in USUARIOS_A_BORRAR if n in por_nombre]
        fuera = [u.username for u in users if u.username not in USUARIOS_A_BORRAR]

        print(f"base: {get_settings().database_url.split('@')[-1].split('/')[0]}")
        print(f"usuarios en la base: {len(users)}\n")

        print("SE BORRAN:")
        for u in objetivo:
            filas = []
            for nombre, modelo in ORDEN:
                n = db.scalar(
                    select(func.count()).select_from(modelo).where(modelo.user_id == u.id)
                )
                if n:
                    filas.append(f"{n} {nombre}")
            detalle = ", ".join(filas) if filas else "solo el usuario"
            print(f"  #{u.id:<3} {u.username:<16} {detalle}")

        print("\nNO SE TOCAN:")
        for nombre in fuera:
            marca = "  <-- PROTEGIDO por el script" if nombre in PROTEGIDOS else ""
            print(f"  {nombre:<16}{marca}")

        faltantes = [n for n in USUARIOS_A_BORRAR if n not in por_nombre]
        if faltantes:
            print(f"\nde la lista blanca no existen (ya borrados): {', '.join(faltantes)}")

        total = {}
        for nombre, modelo in ORDEN:
            ids = [u.id for u in objetivo]
            if not ids:
                break
            n = db.scalar(
                select(func.count()).select_from(modelo).where(modelo.user_id.in_(ids))
            )
            total[nombre] = n
        resumen = ", ".join(f"{n} {nombre}" for nombre, n in total.items() if n)
        print(f"\ntotal a borrar: {len(objetivo)} usuarios, {resumen}")

        if not ejecutar:
            print("\nDRY-RUN: no se borró nada. Para hacerlo de verdad, agregá --yes.")
            return 0

        if not objetivo:
            print("\nnada que borrar.")
            return 0

        for nombre, modelo in ORDEN:
            db.execute(delete(modelo).where(modelo.user_id.in_([u.id for u in objetivo])))
        db.execute(delete(User).where(User.id.in_([u.id for u in objetivo])))
        db.commit()

        print(f"\nBORRADOS {len(objetivo)} usuarios y sus datos. Quedan {len(fuera)} usuarios.")
        return 0
    except Exception:
        db.rollback()
        print("\nERROR: no se borró nada (transacción revertida).", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
