"""Seed de categorías y billeteras por usuario.

Cada usuario tiene SUS categorías (mismo set inicial, después cada uno puede
divergir) y su billetera "General". Se siembran al registrarse, no al arrancar
el servidor: el arranque no sabe qué usuarios van a existir.
"""
from __future__ import annotations

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from .models import Account, Category, Transaction, User

# La billetera por defecto: todo movimiento que no se imputa a una billetera
# concreta cae acá. Sin esto el patrimonio total podría perder plata, porque un
# movimiento sin `cuenta_id` no sumaría en ninguna billetera.
DEFAULT_ACCOUNT_NAME = "General"

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


def seed_user_categories(db: Session, user: User) -> int:
    """Crea las categorías iniciales del usuario. Devuelve cuántas creó."""
    existing = {
        name
        for (name,) in db.execute(
            select(Category.name).where(Category.user_id == user.id)
        ).all()
    }
    created = 0
    for name, kind in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(user_id=user.id, name=name, kind=kind))
            created += 1
    if created:
        db.commit()
    return created


def default_account(db: Session, user_id: int) -> Account:
    """La billetera «General» del usuario, creándola si no existe.

    Nace en 0 a propósito: `apertura_cents` compensa el neto de los movimientos
    que ya estaban cargados sin billetera, porque esa plata ya está reflejada en
    los saldos reales que el usuario declara al crear sus billeteras. Sin el
    ajuste, el patrimonio arrancaría desviado por el histórico.

    Así «General» queda en cero y de ahí en adelante acumula sólo los
    movimientos sin asignar que se registran nuevos (que sí son plata real que
    entra o sale, y por eso cuentan en el patrimonio).
    """
    acc = db.scalar(
        select(Account).where(
            Account.user_id == user_id, Account.name == DEFAULT_ACCOUNT_NAME
        )
    )
    if acc is None:
        acc = Account(
            user_id=user_id,
            name=DEFAULT_ACCOUNT_NAME,
            kind="otro",
            apertura_cents=-neto_huerfanos(db, user_id),
            notes="Movimientos sin billetera asignada.",
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)
    return acc


def neto_huerfanos(db: Session, user_id: int) -> int:
    """Ingresos − gastos de los movimientos que todavía no tienen billetera."""
    return int(
        db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.type == "income", Transaction.amount_cents),
                            else_=-Transaction.amount_cents,
                        )
                    ),
                    0,
                )
            ).where(Transaction.user_id == user_id, Transaction.cuenta_id.is_(None))
        )
        or 0
    )


def seed_user_accounts(db: Session, user: User) -> int:
    """Crea la billetera «General» e imputa a ella los movimientos huérfanos.

    Corre en el arranque del servidor, NO en cada request: el backfill escribe
    y solo hace falta una vez (los movimientos que se crean después siempre
    llegan resueltos a una billetera, en la API o en las herramientas).

    Es idempotente: sólo toca `cuenta_id IS NULL`, así que un movimiento ya
    asignado por el usuario nunca se toca.
    """
    acc = default_account(db, user.id)
    res = db.execute(
        update(Transaction)
        .where(Transaction.user_id == user.id, Transaction.cuenta_id.is_(None))
        .values(cuenta_id=acc.id)
    )
    db.commit()
    return int(res.rowcount or 0)
