"""Herramientas de importación CSV y detección de anomalías."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ... import importer
from ...analytics import detect_anomalies
from ..provider import get_provider


# Un clasificador por usuario (se entrena a demanda con SUS datos).
# Compartir uno global filtraría patrones de gasto entre usuarios.
_classifiers: dict[int, importer.LocalClassifier] = {}


def _get_classifier(db: Session, user_id: int) -> importer.LocalClassifier:
    clf = _classifiers.get(user_id)
    if clf is None:
        clf = importer.LocalClassifier()
        _classifiers[user_id] = clf
    if not clf.is_ready():
        n = clf.train(db, user_id)
        if n:
            print(f"[classifier] Entrenado con {n} transacciones")
    return clf


def preview_importar_csv(db: Session, args: dict, user_id: int) -> str:
    """Vista previa de lo que se importaría (sin escribir)."""
    path = str(args.get("archivo", "")).strip()
    if not path:
        raise ValueError("Falta el parámetro 'archivo' (ruta al CSV).")

    clf = _get_classifier(db, user_id)
    preview = importer.preview_csv(db, user_id, path, clf)

    if preview.total_rows == 0:
        return "El archivo está vacío o no se pudo leer."

    lines = [
        f"📄 Vista previa de «{path}»:",
        f"  Filas totales: {preview.total_rows}",
        f"  Nuevas para importar: {preview.new_rows}",
        f"  Duplicadas (ya existen): {preview.duplicates}",
        f"  Errores de formato: {preview.errors}",
    ]
    if preview.categories_missing:
        lines.append(f"  ⚠️ Categorías no encontradas: {', '.join(preview.categories_missing)}")
    if preview.sample:
        lines.append("\nEjemplos:")
        for s in preview.sample:
            cat = s.get("categoria", "?")
            lines.append(f"  {s['fecha']} | {s['tipo']} | ${s['monto']:,.2f} | {s['descripcion'][:40]} | cat: {cat}")
    lines.append("\nPara importar de verdad: «importá el CSV /ruta/archivo.csv»")
    return "\n".join(lines)


def importar_csv(db: Session, args: dict, user_id: int) -> str:
    """Importa un CSV de movimientos bancarios."""
    path = str(args.get("archivo", "")).strip()
    if not path:
        raise ValueError("Falta el parámetro 'archivo' (ruta al CSV).")

    clf = _get_classifier(db, user_id)
    result = importer.import_csv(db, user_id, path, clf, confirm=True)

    lines = [f"✅ Importación completada: {result.created} movimientos nuevos"]
    if result.skipped_duplicates:
        lines.append(f"  Duplicados omitidos: {result.skipped_duplicates}")
    if result.errors:
        lines.append(f"  Errores: {len(result.errors)}")
        for e in result.errors[:5]:
            lines.append(f"    - {e}")
        if len(result.errors) > 5:
            lines.append(f"    ... y {len(result.errors) - 5} más")
    return "\n".join(lines)


def entrenar_clasificador(db: Session, args: dict, user_id: int) -> str:
    """Reentrena el clasificador local con todos los datos actuales."""
    clf = importer.LocalClassifier()
    _classifiers[user_id] = clf
    n = clf.train(db, user_id)
    if n:
        return f"Clasificador entrenado con {n} transacciones."
    return "No hay suficientes transacciones categorizadas para entrenar (mínimo 10)."


def listar_anomalias(db: Session, args: dict, user_id: int) -> str:
    """Detecta gastos que se desvían mucho del patrón histórico."""
    mes = str(args.get("mes", "")).strip() or None
    threshold = float(args.get("umbral", 150.0))

    anomalies = detect_anomalies(db, mes, threshold, user_id)

    if not anomalies:
        return "No se detectaron anomalías (ningún gasto supera el umbral)."

    lines = [f"🔍 Anomalías detectadas (umbral: {threshold:.0f}% sobre media histórica):"]
    for a in anomalies[:20]:
        lines.append(
            f"  #{a.id} {a.date.isoformat()} | {a.category} | ${a.amount_cents/100:,.2f} "
            f"(esperado ~${a.expected_cents/100:,.2f}) | +{a.deviation_pct:.0f}% | {a.description[:50]}"
        )
    if len(anomalies) > 20:
        lines.append(f"  ... y {len(anomalies) - 20} más")
    return "\n".join(lines)


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "preview_importar_csv",
            "description": "Muestra una vista previa de lo que importaría un CSV (filas nuevas, duplicados, categorías faltantes) SIN escribir en la base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo": {"type": "string", "description": "Ruta al archivo CSV (ej: /home/franco/movimientos.csv)"},
                },
                "required": ["archivo"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "importar_csv",
            "description": "Importa un CSV de movimientos bancarios. Categoriza automáticamente usando el clasificador local entrenado con tus datos. Omite duplicados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo": {"type": "string", "description": "Ruta al archivo CSV"},
                },
                "required": ["archivo"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "entrenar_clasificador",
            "description": "Reentrena el clasificador local (TF-IDF + LogisticRegression) con todas las transacciones categorizadas existentes.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_anomalias",
            "description": "Detecta gastos del mes que superan significativamente el promedio histórico de su categoría (ej: un gasto 3x mayor al habitual).",
            "parameters": {
                "type": "object",
                "properties": {
                    "mes": {"type": "string", "description": "Mes en formato YYYY-MM (opcional, default = actual)"},
                    "umbral": {"type": "number", "description": "Porcentaje de desviación para considerar anomalía (default 150 = 2.5x la media)"},
                },
                "additionalProperties": False,
            },
        },
    },
]

IMPLS = {
    "preview_importar_csv": preview_importar_csv,
    "importar_csv": importar_csv,
    "entrenar_clasificador": entrenar_clasificador,
    "listar_anomalias": listar_anomalias,
}