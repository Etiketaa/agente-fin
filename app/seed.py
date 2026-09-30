"""Seed de categorías por usuario.

Cada usuario tiene SUS categorías (mismo set inicial, después cada uno puede
divergir). Se siembran al registrarse, no al arrancar el servidor: el arranque
no sabe qué usuarios van a existir.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, User

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
