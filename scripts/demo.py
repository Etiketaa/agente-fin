"""Carga datos de ejemplo (opcional) para ver la app con contenido.

Uso:  python -m scripts.demo
Para empezar de cero: borrá finanzas.db y reiniciá el servidor.

Es idempotente respecto de las categorías, pero corre los montos siempre: si lo
ejecutás dos veces vas a duplicar los movimientos.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.config import get_settings, BASE_DIR  # noqa: F401  (asegura .env cargado)
from app.auth import hash_password
from app.db import Base, SessionLocal, engine
from app.agent.tools import money_to_cents
from app.models import Budget, Category, SavingsGoal, Transaction, User
from app.seed import seed_user_categories

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo1234"


def main() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == DEMO_USERNAME))
        if user is None:
            user = User(username=DEMO_USERNAME,
                        password_hash=hash_password(DEMO_PASSWORD))
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Usuario demo creado: {DEMO_USERNAME} / {DEMO_PASSWORD}")
        seed_user_categories(db, user)
        cats = {
            c.name: c
            for c in db.scalars(
                select(Category).where(Category.user_id == user.id)
            ).all()
        }
        today = date.today()
        first = today.replace(day=1)
        fuentes = {"Sueldo": "Empresa (sueldo)", "Freelance": "Cliente QA remoto"}
        samples_extra = [
            ("income", 95000, "Freelance", "Landings", first + timedelta(days=3), "Cliente idiomas"),
            ("income", 55000, "Freelance", "Ajustes web", first + timedelta(days=9), "Cliente idiomas"),
        ]
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

        # Objetivos de ahorro. El saldo se deriva de los movimientos con
        # goal_id, así que los aportes van como transactions más abajo.
        goals = {
            nombre: SavingsGoal(
                user_id=user.id,
                name=nombre,
                target_cents=money_to_cents(monto),
                target_date=fecha,
                notes=nota,
            )
            for nombre, monto, fecha, nota in [
                ("Fondo de emergencia", 1200000, today + timedelta(days=180), "6 meses de gastos"),
                ("Moto nueva", 2500000, today + timedelta(days=300), "Service + cubiertas"),
            ]
        }
        db.add_all(goals.values())
        db.commit()
        for g in goals.values():
            db.refresh(g)

        db.add_all(
            [
                Transaction(user_id=user.id, type=t, amount_cents=money_to_cents(m),
                            category_id=cats[c].id, description=d, date=f,
                            source=fuentes.get(c) if t == "income" else None)
                for t, m, c, d, f in samples
            ]
            + [
                Transaction(user_id=user.id, type=t, amount_cents=money_to_cents(m),
                            category_id=cats[c].id, description=d, date=f, source=s)
                for t, m, c, d, f, s in samples_extra
            ]
            # Aportes al fondo de emergencia: además de contar en el balance,
            # suman al progreso del objetivo.
            + [
                Transaction(user_id=user.id, type="expense",
                            amount_cents=money_to_cents(monto),
                            category_id=cats["Otros"].id, description=desc,
                            date=first + timedelta(days=dia), goal_id=goals["Fondo de emergencia"].id)
                for monto, desc, dia in [
                    (60000, "Aporte mensual al fondo", 7),
                    (60000, "Aporte mensual al fondo", 21),
                ]
            ]
        )
        db.add_all(
            Budget(user_id=user.id, category_id=cats[c].id, amount_cents=money_to_cents(m))
            for c, m in [("Comida", 180000), ("Motos", 90000), ("Ocio", 60000)]
        )
        db.commit()
        print("Datos de ejemplo cargados (incluye objetivos de ahorro y presupuestos).")
    finally:
        db.close()


if __name__ == "__main__":
    main()