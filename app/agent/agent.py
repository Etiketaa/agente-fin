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

MAX_ITERS = 6

_SETTINGS = get_settings()

SYSTEM_PROMPT = f"""Sos el asistente financiero personal de Franco. Hoy es {date.today().isoformat()}. Operás sobre su sistema de finanzas personales: ingresos, gastos, categorías y balance.

La moneda es {_SETTINGS.currency}.

Reglas:
1. Respondé SIEMPRE en español, breve y con números claros.
2. Nunca inventes datos: para conocer información de las finanzas usá las herramientas disponibles y devolvé lo que devuelven.
3. Si una herramienta devuelve un error (por ejemplo una categoría inexistente), corregí el pedido usando la información del error. Si no, preguntale a Franco con una pregunta corta.
4. Si te falta información necesaria, pedila con una pregunta corta.
5. Si Franco te pide eliminar una transacción o registrar un monto grande, ejecutá la herramienta igual: el sistema frenará la acción y le pedirá confirmación.
6. Mostrá los montos con separador de miles, por ejemplo: $1.234.567."""


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


def _execute(tc: ToolCall, db: Session) -> str:
    try:
        return T.execute_tool(tc.name, tc.arguments, db)
    except (ValueError, TypeError) as exc:
        return f"Error ejecutando {tc.name}: {exc}"


def run_agent(messages: list[dict], db: Session, pre_confirmed: dict | None = None) -> dict:
    """Corre el bucle agente→herramientas.

    - `pre_confirmed`: cuando el usuario confirmó una acción sensible, se
      ejecuta primero esa acción y se continúa el diálogo.
    """
    provider = get_provider()
    full: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    full.extend(_clean(messages))

    executed_first = False
    if pre_confirmed:
        tc = ToolCall(pre_confirmed["tool"], pre_confirmed["args"])
        call_id = "call_confirmed"
        full.append(_assistant_tool_message(tc, call_id))
        full.append({"role": "tool", "tool_call_id": call_id, "content": _execute(tc, db)})
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
        full.append({"role": "tool", "tool_call_id": call_id, "content": _execute(tc, db)})
        # continuamos el bucle: el modelo verá el resultado y decidirá

    return _answer("No llegué a completar la respuesta. Probá reformular la pregunta.")