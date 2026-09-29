"""Importador CSV/Excel con clasificador local (TF-IDF + sklearn).

Uso:
    from app.importer import import_csv, train_classifier
    import_csv(db, "movimientos.csv")  # preview=True para ver antes de confirmar
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, Transaction, Vehicle
from .analytics import month_bounds
from .config import get_settings


# ---------------------------------------------------------------------------
# Utilidades de moneda / parsing
# ---------------------------------------------------------------------------

_CENTS_RE = re.compile(r"[\d.,]+")


def parse_amount(text: str) -> int:
    """Convierte '1.234,56' / '1234,56' / '1234.56' / '1,234.56' → centavos."""
    if not text:
        return 0
    # Normalizar: quitar espacios, separador de miles, dejar solo dígitos y coma/punto decimal
    t = text.strip().replace(" ", "")
    # Heurística: si hay tanto coma como punto, el último es decimal
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        # Solo comas: si hay una sola y 2-3 dígitos después → decimal
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) <= 3:
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
    # A esta altura t debería ser número con punto decimal opcional
    try:
        return int((Decimal(t) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except Exception:
        # fallback: extraer dígitos
        digits = re.sub(r"[^\d]", "", t)
        return int(digits) * 100 if digits else 0


def parse_date(text: str) -> date:
    """Acepta YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, YYYY/MM/DD."""
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Fecha no reconocida: '{text}'. Usá YYYY-MM-DD o DD/MM/YYYY.")


def detect_type(row: dict, amount: int, default_type: str = "expense") -> str:
    """Infiere income/expense si no viene explícito."""
    # Buscar claves comunes
    for k in ("tipo", "type", "tipo_movimiento", "debito_credito"):
        v = str(row.get(k, "")).strip().lower()
        if v in ("ingreso", "income", "credito", "crédito", "c", "+"):
            return "income"
        if v in ("gasto", "expense", "debito", "débito", "d", "-"):
            return "expense"
    # Heurística por monto y descripción
    desc = str(row.get("descripcion", row.get("description", ""))).lower()
    if any(w in desc for w in ("sueldo", "salary", "ingreso", "cobro", "transferencia recibida")):
        return "income"
    return default_type


def normalize_desc(text: str) -> str:
    """Normaliza descripción para dedup y clasificación."""
    return re.sub(r"\s+", " ", text.strip().lower())


def row_hash(date_: date, amount: int, desc: str, type_: str) -> str:
    """Hash determinista para detectar duplicados (MD5 truncado a 32 chars)."""
    raw = f"{date_.isoformat()}|{amount}|{type_}|{normalize_desc(desc)}"
    return hashlib.md5(raw.encode()).hexdigest()  # 32 chars


# ---------------------------------------------------------------------------
# Clasificador local (TF-IDF + LogisticRegression)
# ---------------------------------------------------------------------------

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False


class LocalClassifier:
    """Clasificador entrenado con tus propios datos (descripción → categoría)."""

    def __init__(self):
        self.pipe: Optional[Pipeline] = None
        self.categories: list[str] = []
        self._trained = False

    def train(self, db: Session) -> int:
        """Entrena con todas las transacciones existentes que tengan categoría."""
        if not _SKLEARN_OK:
            return 0
        txs = db.scalars(
            select(Transaction).join(Category).where(Transaction.category_id.is_not(None))
        ).all()
        if len(txs) < 10:
            return 0
        X = [normalize_desc(tx.description) for tx in txs]
        y = [tx.category.name for tx in txs]
        self.categories = sorted(set(y))
        self.pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.9)),
            ("clf", LogisticRegression(max_iter=200, class_weight="balanced")),
        ])
        self.pipe.fit(X, y)
        self._trained = True
        return len(txs)

    def predict(self, description: str) -> tuple[str, float] | None:
        """Devuelve (categoría, confidence 0-1) o None si no entrenado."""
        if not self._trained or not self.pipe:
            return None
        proba = self.pipe.predict_proba([normalize_desc(description)])[0]
        idx = proba.argmax()
        return self.pipe.classes_[idx], float(proba[idx])

    def is_ready(self) -> bool:
        return self._trained and _SKLEARN_OK


# ---------------------------------------------------------------------------
# Importador principal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImportPreview:
    total_rows: int
    new_rows: int
    duplicates: int
    errors: int
    categories_missing: list[str]
    sample: list[dict]  # primeras 10 filas para mostrar


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped_duplicates: int
    errors: list[str]


def _read_csv(path: str) -> list[dict]:
    """Lee CSV con encoding flexible y detecta delimitador."""
    with open(path, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample, delimiters=",;\t|")
        except Exception:
            dialect = csv.get_dialect("excel")
        reader = csv.DictReader(f, dialect=dialect)
        # Normalizar nombres de columnas
        rows = []
        for row in reader:
            clean = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if v}
            rows.append(clean)
        return rows


def _infer_columns(row: dict) -> dict:
    """Mapea columnas comunes a nombres estándar."""
    aliases = {
        "fecha": ["fecha", "date", "dia", "día"],
        "descripcion": ["descripcion", "description", "detalle", "concepto", "nombre"],
        "monto": ["monto", "importe", "amount", "valor", "total", "precio"],
        "tipo": ["tipo", "type", "tipo_movimiento", "debito_credito", "debito", "credito"],
        "categoria": ["categoria", "category", "cat"],
        "cuenta": ["cuenta", "account", "tarjeta", "banco"],
    }
    out = {}
    for std, options in aliases.items():
        for opt in options:
            if opt in row:
                out[std] = row[opt]
                break
    return out


def preview_csv(db: Session, path: str, classifier: Optional[LocalClassifier] = None) -> ImportPreview:
    """Analiza el CSV y devuelve preview sin escribir en BD."""
    rows = _read_csv(path)
    if not rows:
        return ImportPreview(0, 0, 0, 0, [], [])

    existing_hashes = {
        h for (h,) in db.execute(select(Transaction.import_hash)).all()
        if h
    }

    # Usar hash simple en memoria para preview
    seen_hashes = set()
    new_count = 0
    dup_count = 0
    err_count = 0
    cats_missing = set()
    sample = []

    for i, raw in enumerate(rows):
        mapped = _infer_columns(raw)
        try:
            dt = parse_date(mapped.get("fecha", ""))
            amt = parse_amount(mapped.get("monto", ""))
            typ = detect_type(mapped, amt)
            desc = mapped.get("descripcion", "")
            cat_name = mapped.get("categoria", "")

            # Categoría: si no viene, intentar clasificar
            cat_id = None
            if cat_name:
                cat = db.scalar(select(Category).where(Category.name.ilike(cat_name)))
                if cat:
                    cat_id = cat.id
                else:
                    cats_missing.add(cat_name)
            elif classifier and classifier.is_ready():
                pred = classifier.predict(desc)
                if pred:
                    cat_name, conf = pred
                    if conf > 0.6:
                        cat = db.scalar(select(Category).where(Category.name == cat_name))
                        if cat:
                            cat_id = cat.id

            h = row_hash(dt, amt, desc, typ)
            if h in seen_hashes or (h in existing_hashes):
                dup_count += 1
            else:
                new_count += 1
                seen_hashes.add(h)
                if len(sample) < 10:
                    sample.append({
                        "fecha": dt.isoformat(),
                        "descripcion": desc or "(sin descripción)",
                        "monto": amt / 100,
                        "tipo": typ,
                        "categoria": cat_name or (pred[0] if classifier and classifier.is_ready() and (pred := classifier.predict(desc)) else "?"),
                        "hash": h,
                    })
        except Exception:
            err_count += 1

    return ImportPreview(
        total_rows=len(rows),
        new_rows=new_count,
        duplicates=dup_count,
        errors=err_count,
        categories_missing=sorted(cats_missing),
        sample=sample,
    )


def import_csv(db: Session, path: str, classifier: Optional[LocalClassifier] = None, confirm: bool = True) -> ImportResult:
    """Importa el CSV a la base de datos.

    Si `confirm=False`, solo hace preview (útil para el agente).
    """
    if confirm:
        preview = preview_csv(db, path, classifier)
        if preview.new_rows == 0:
            return ImportResult(0, preview.duplicates, ["Nada nuevo para importar"])

    rows = _read_csv(path)
    created = 0
    skipped = 0
    errors: list[str] = []
    seen_hashes = set()

    # Cargar hashes existentes
    existing_hashes = {
        h for (h,) in db.execute(select(Transaction.extra_data)).all()  # type: ignore
        if h
    }

    for raw in rows:
        mapped = _infer_columns(raw)
        try:
            dt = parse_date(mapped.get("fecha", ""))
            amt = parse_amount(mapped.get("monto", ""))
            typ = detect_type(mapped, amt)
            desc = mapped.get("descripcion", "")
            cat_name = mapped.get("categoria", "")

            cat_id = None
            if cat_name:
                cat = db.scalar(select(Category).where(Category.name.ilike(cat_name)))
                if cat:
                    cat_id = cat.id
                else:
                    errors.append(f"Categoría no encontrada: '{cat_name}' en fila {desc[:40]}")
                    continue
            elif classifier and classifier.is_ready():
                pred = classifier.predict(desc)
                if pred:
                    cat_name, conf = pred
                    if conf > 0.6:
                        cat = db.scalar(select(Category).where(Category.name == cat_name))
                        if cat:
                            cat_id = cat.id

            if cat_id is None:
                errors.append(f"Sin categoría para: {desc[:40]}")
                continue

            h = row_hash(dt, amt, desc, typ)
            if h in seen_hashes or h in existing_hashes:
                skipped += 1
                continue

            tx = Transaction(
                type=typ,
                amount_cents=amt,
                description=desc,
                date=dt,
                category_id=cat_id,
                import_hash=h,
            )
            db.add(tx)
            created += 1
            seen_hashes.add(h)

        except Exception as e:
            errors.append(f"Fila {raw}: {e}")

    if created:
        db.commit()
    return ImportResult(created, skipped, errors)