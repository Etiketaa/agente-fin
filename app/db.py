"""Motor de base de datos y sesiones."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    _settings.database_url,
    connect_args=_connect_args,
    # Neon (y serverless en general) cierra conexiones idle. pool_pre_ping
    # hace un ping barato antes de cada uso y descarta las muertas, en vez
    # de fallar el request del usuario con "server closed the connection".
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()