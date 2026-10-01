"""
Bucle del agente: sistema → modelo → herramientas → resultado → modelo...

Flujo:
1. El modelo decide si responder texto o llamar una herramienta.
2. Si la llamada es SENSIBLE y no viene confirmada → devolvemos la
   propuesta `pending_action` (el frontend la muestra al usuario).
3. Si no es sensible (o ya vino confirmada) → se ejecuta y el resultado
   se le devuelve al modelo para que continúe.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from ..config import get_settings
from . import tools as T
from .provider import ToolCall, get_provider
from ..db import SessionLocal
from ..models import Category
from sqlalchemy import select

MAX_ITERS = 6

_SETTINGS = get_settings()


def _categories_hint(user_id: int) -> str:
    """Lista corta de categorías DEL USUARIO para que el modelo no pregunte."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Category.name, Category.kind)
            .where(Category.user_id == user_id)
            .order_by(Category.kind, Category.name)
        ).all()
        income = ", ".join(n for n, k in rows if k == "income") or "(ninguna)"
        expense = ", ".join(n for n, k in rows if k == "expense") or "(ninguna)"
        return f"Categorías válidas — ingreso: {income}. Gasto: {expense}."
    finally:
        db.close()


SYSTEM_PROMPT_TEMPLATE = """Sos el asistente financiero personal de Franco. Hoy es {today}. Operás sobre su sistema de finanzas personales: ingresos, gastos, categorías, objetivos de ahorro, presupuestos mensuales y vencimientos.

La moneda es {currency}.

{categories_hint}

Reglas:
1. Respondé SIEMPRE en español, breve y con números claros.
2. Nunca inventes datos: para conocer información de las finanzas usá las herramientas disponibles y devolvé lo que devuelven.
3. Si una herramienta devuelve un error (p. ej. categoría inexistente), corregí el pedido usando la información del error. Si no, preguntale a Franco con una pregunta corta.
4. Si te falta información necesaria, pedila con una pregunta corta.
5. Si Franco te pide eliminar algo o registrar un monto grande, ejecutá la herramienta igual: el sistema frenará la acción y le pedirá confirmación.
6. Mostrá los montos con separador de miles, por ejemplo: $1.234.567.
7. Sobre presupuestos: avisá proactivamente cuando Franco pregunte cómo viene, y no escondas los estados "atencion" o "excedido". Si al ritmo actual va a pasar el límite, decilo.
8. Un movimiento con "objetivo" asignado es dinero separado para una meta: además de contar en el balance, suma al progreso del objetivo. No lo cuentes dos veces en la respuesta. Si la meta es una *recaudación*, el progreso es ingresos asignados − gastos asignados: lo que entró de otros menos lo que ya se usó de esa bolsa.
9. Podés sugerir crear un presupuesto o un objetivo si los datos lo justifican, pero nunca lo hagas sin que Franco lo pida.
10. Sobre vencimientos y alertas: si Franco pregunta qué tiene pendiente, qué vence pronto o si hay algo que requiera atención, usá listar_alertas (consolida vencimientos, presupuestos, objetivos y anomalías). Pagar un vencimiento genera el gasto real y, si es mensual, crea el siguiente automáticamente: avisalo en la respuesta.
"""


def _answer(reply: str | None, pending: dict | None = None) -> dict:
    return {"reply": reply, "pending_action": pending}


def _clean(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out


def _assistant_tool_message(tc: ToolCall, call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
        ],
    }


def _execute(tc: ToolCall, db: Session, user_id: int) -> str:
    try:
        return T.execute_tool(tc.name, tc.arguments, db, user_id)
    except (ValueError, TypeError) as exc:
        return f"Error ejecutando {tc.name}: {exc}"


def run_agent(messages: list[dict], db: Session, pre_confirmed: dict | None = None,
              user_id: int = 0) -> dict:
    """Corre el bucle agente→herramientas.

    - `pre_confirmed`: cuando el usuario confirmó una acción sensible, se
      ejecuta primero esa acción y se continúa el diálogo.
    - `user_id`: el dueño de todos los datos que el agente puede ver y tocar.
    """
    provider = get_provider()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        today=date.today().isoformat(),
        currency=_SETTINGS.currency,
        categories_hint=_categories_hint(user_id),
    )
    full: list[dict] = [{"role": "system", "content": system_prompt}]
    full.extend(_clean(messages))

    executed_first = False
    if pre_confirmed:
        tc = ToolCall(pre_confirmed["tool"], pre_confirmed["args"])
        call_id = "call_confirmed"
        full.append(_assistant_tool_message(tc, call_id))
        full.append({"role": "tool", "tool_call_id": call_id, "content": _execute(tc, db, user_id)})
        executed_first = True

    for i in range(MAX_ITERS):
        text, tool_calls = provider.chat(full, T.TOOLS)

        if not tool_calls:
            return _answer(text)

        tc = tool_calls[0]

        # Acción sensible sin confirmar → pedir confirmación, NO ejecutar.
        if T.is_sensitive(tc.name, tc.arguments):
            return _answer(
                "⚠️ Para esta acción necesito tu confirmación.",
                pending={
                    "tool": tc.name,
                    "args": tc.arguments,
                    "summary": T.summarize_action(tc.name, tc.arguments),
                },
            )

        call_id = f"call_{tc.name}_{i}"
        full.append(_assistant_tool_message(tc, call_id))
        full.append({"role": "tool", "tool_call_id": call_id, "content": _execute(tc, db, user_id)})
        # continuamos el bucle: el modelo verá el resultado y decidirá

    return _answer("No llegué a completar la respuesta. Probá reformular la pregunta.")