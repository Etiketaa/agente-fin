"""Punto de entrada: app FastAPI + estáticos + seed de categorías."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .api import router
from .db import Base, SessionLocal, engine
from .models import Category

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

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
    Base.metadata.create_all(engine)
    seed_categories()
    yield


app = FastAPI(title="Finanzas Personales", lifespan=lifespan)
app.include_router(router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")