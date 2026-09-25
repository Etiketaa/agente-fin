# 💰 Finanzas Personales — v1

Sistema de finanzas personales con **agente de IA** integrado.

Este es el "laboratorio" del proyecto: primero lo usás vos, después la
arquitectura se convierte en un servicio para clientes.

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | HTML/CSS/JS vanilla (web app responsive, servida por el backend) |
| Backend | Python + FastAPI |
| Base de datos | SQLAlchemy + SQLite (v1) → PostgreSQL cuando haya multiusuario |
| Agente | Tool-calling con **proveedor intercambiable**: OpenAI / compatible / modo demo |

## Puesta en marcha

```bash
cd finanzas
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# (opcional) datos de ejemplo para verla con contenido
python -m scripts.demo

# configurar API key del agente (sin key → modo demo)
cp .env.example .env
#   OPENAI_API_KEY=sk-...
#   (opcional) OPENAI_BASE_URL para OpenRouter, Ollama, LM Studio, vLLM...

uvicorn app.main:app --reload
```

Abrí **http://127.0.0.1:8000**

> Para empezar de cero borrá `finanzas.db` y reiniciá el servidor.

## Cómo funciona el agente

```
Frontend (chat) → POST /api/agent/chat → bucle: modelo → tools → modelo → respuesta
                             ↓ si llama una herramienta SENSIBLE
                 pending_action → el frontend muestra: Confirmar / Cancelar
                             ↓ confirmación
                 POST /api/agent/confirm → se ejecuta y continúa el diálogo
```

### Herramientas del agente

| Herramienta | Qué hace | ¿Sensible? |
|---|---|---|
| `listar_transacciones` | Lista movimientos con filtros | No |
| `calcular_balance` | Ingresos − gastos en un período | No |
| `resumen_por_categoria` | Totales por categoría | No |
| `listar_categorias` | Categorías disponibles | No |
| `registrar_transaccion` | Da de alta un ingreso/gasto | Sí, si monto ≥ `SENSITIVE_AMOUNT` |
| `eliminar_transaccion` | Borra un movimiento | **Siempre** |

Las acciones sensibles **nunca se ejecutan** sin tu confirmación: el backend
devuelve la propuesta, vos la aprobás explícitamente en la UI y recién ahí se
ejecuta. Es una invariante de seguridad del sistema, no una convención del modelo.

### Modelo intercambiable (punto clave de la arquitectura)

Todo el sistema habla con `app/agent/provider.py`. Cambiar de modelo es editar
dos variables de entorno:

```bash
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# OpenRouter (mismo código)
OPENAI_API_KEY=<tu key de openrouter>
OPENAI_BASE_URL=https://openrouter.ai/api/v1

# Modelos locales (Ollama / LM Studio / vLLM — mismo código)
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=llama3.1

# Sin key → modo demo (MockProvider, sin costo)
# LLM_MOCK=1 para forzarlo aunque exista key
```

Para agregar un proveedor que no sea OpenAI-compatible (p. ej. Anthropic),
implementás la misma interfaz (`chat(messages, tools) -> (texto, tool_calls)`)
en `provider.py` y la registrás en `get_provider`. Nada más cambia.

## Estructura

```
finanzas/
├── app/
│   ├── config.py          # configuración vía .env
│   ├── db.py              # motor + sesiones (SQLite → PostgreSQL después)
│   ├── models.py          # Category, Transaction (montos en centavos)
│   ├── schemas.py         # contratos Pydantic de la API
│   ├── api.py             # endpoints REST
│   ├── main.py            # app FastAPI + seed de categorías
│   └── agent/
│       ├── provider.py    # ← capa de proveedor intercambiable
│       ├── tools.py       # herramientas: schema + implementación
│       └── agent.py       # bucle agente ↔ herramientas + confirmación
├── static/                # frontend (sin build step)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── scripts/demo.py        # datos de ejemplo
└── requirements.txt
```

## Decisiones de v1 (y por qué)

- **Montos en centavos (enteros)**: nunca floats en la base; los errores de
  redondeo en dinero son cargos que después cuesta explicar.
- **SQLite + SQLAlchemy**: el salto a PostgreSQL es cambiar `DATABASE_URL`.
  Para multiusuario (los clientes) ya está listo.
- **Sin build step en el frontend**: la v2 puede sumar React/Next cuando el
  panel crezca; el backend queda igual.
- **Confirmación en el backend, no en el frontend**: aunque mañana el chat lo
  use WhatsApp o una API, la regla "acciones sensibles requieren confirmación"
  sigue vigente.

## Roadmap (iteraciones siguientes)

1. **Objetivos de ahorro** + separación de dinero por objetivo.
2. **Presupuesto mensual** por categoría con alertas.
3. **Gastos específicos de motos** (combustible, mantenimiento, seguro) con su tabla.
4. **Detección de gastos que se disparan** (comparación contra el promedio).
5. **Alertas y tareas automáticas** (vencimientos, por ejemplo).
6. **Autenticación + multiusuario** (el paso a PostgreSQL y a "sistema para clientes").