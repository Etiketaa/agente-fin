# 💰 Finanzas Personales

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

# NVIDIA API (endpoint compatible con OpenAI)
#   OPENAI_API_KEY=nvapi-...
#   OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1
#   OPENAI_MODEL=nvidia/nemotron-3-super-120b-a12b

uvicorn app.main:app --reload
```

Abrí **http://127.0.0.1:8000**

> Para empezar de cero borrá `finanzas.db` y reiniciá el servidor.

### Verificación del proveedor

Con el servidor corriendo, la sonda confirma que el proveedor habla el
protocolo de tool-calling que necesita el agente:

```bash
.venv/bin/python -m scripts.prove_provider
```

El smoke test recorre el CRUD, objetivos, presupuestos, una consulta al agente
y la confirmación de acciones sensibles:

```bash
.venv/bin/python -m scripts.smoke
```

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
| `listar_transacciones` | Lista movimientos con filtros (incluye filtro por objetivo) | No |
| `calcular_balance` | Ingresos − gastos en un período | No |
| `resumen_por_categoria` | Totales por categoría | No |
| `listar_categorias` | Categorías disponibles | No |
| `listar_objetivos` | Objetivos con progreso y ritmo necesario | No |
| `listar_presupuestos` | Presupuestos del mes con alertas y proyección | No |
| `registrar_transaccion` | Da de alta un ingreso/gasto, opcionalmente a un objetivo | Sí, si monto ≥ `SENSITIVE_AMOUNT` |
| `crear_objetivo` | Crea una meta de ahorro | No (es una meta, no mueve dinero) |
| `definir_presupuesto` | Define o actualiza el tope mensual de una categoría | No |
| `listar_vehiculos` / `crear_vehiculo` | Vehículos para etiquetar gastos (moto, auto) | No |
| `preview_importar_csv` | Vista previa de un CSV (nuevas, duplicadas, sin categoría) | No |
| `importar_csv` | Importa el CSV con categorización automática | **Siempre** (escribe muchos registros) |
| `entrenar_clasificador` | Reentrena el clasificador local con tus datos | No |
| `listar_anomalias` | Gastos fuera de lo habitual vs media histórica | No |
| `listar_vencimientos` | Pagos futuros con estado (vencido/próximo/pendiente) | No |
| `crear_vencimiento` | Carga un pago futuro, único o mensual | No (es una intención, no mueve dinero) |
| `pagar_vencimiento` | Marca pagado, genera el gasto y crea el siguiente si es mensual | **Siempre** |
| `listar_alertas` | Centro de alertas consolidado | No |
| `eliminar_transaccion` | Borra un movimiento | **Siempre** |
| `eliminar_objetivo` | Borra un objetivo (falla si tiene aportes) | **Siempre** |
| `eliminar_presupuesto` | Borra un presupuesto | **Siempre** |
| `eliminar_vehiculo` / `eliminar_vencimiento` | Borran su registro | **Siempre** |

Las acciones sensibles **nunca se ejecutan** sin tu confirmación: el backend
devuelve la propuesta, vos la aprobás explícitamente en la UI y recién ahí se
ejecuta. Es una invariante de seguridad del sistema, no una convención del modelo.

Notá la asimetría entre **crear un objetivo por $8.000.000** (no pide
confirmación: es una intención) y **apartar $150.000 para él** (pide
confirmación: es dinero que se mueve). La regla no es "todo monto grande", es
"todo lo que escribe o destruye registro".

## Objetivos de ahorro

Un objetivo es una meta (`target_cents`) con fecha límite opcional.

**El saldo no se guarda: se deriva.** La tabla `savings_goals` no tiene columna
de progreso; el avance sale de sumar los movimientos que tienen su
`goal_id`. Consecuencia práctica: el objetivo nunca puede desincronizarse del
libro de movimientos, porque no hay un segundo número que pueda mentir.

Un movimiento asignado a un objetivo:

- suma a su progreso, y
- **también cuenta en el balance general**, porque el dinero efectivamente salió
  de tu cuenta.

Registrás el aporte desde el formulario ("Ahorro" → objetivo) o por chat
(*"guardá un aporte de 100.000 al fondo de emergencia"*).

No se puede borrar un objetivo que tiene movimientos asignados: se rechaza con
un 409 y el detalle de cuántos son. Desvincularlos en silencio dejaría
movimientos apuntando a un objetivo inexistente.

## Presupuestos mensuales y alertas

Una fila por categoría con un tope mensual. `BUDGET_ALERT_PCT` (0.8 por
defecto) define desde qué porcentaje empieza a avisar. El estado sale de
comparar lo gastado en el mes calendario contra el tope:

| Estado | Cuándo | Cómo se ve |
|---|---|---|
| `ok` | menos del umbral | 🟢 |
| `atencion` | del umbral al 100% | 🟡 fondo ámbar |
| `excedido` | pasado el 100% | 🔴 fondo rojo |

Además del estado, cada presupuesto trae una **proyección** a ritmo actual
(`gastado / días transcurridos × días del mes`) y los días que faltan del mes.
Alcanzar el 80% de Motos con 2 días restantes no avisa lo mismo que con 20, y
por eso el agente lo dice explícitamente.

La alerta vive en dos lugares y sale de la **misma función** (`app/analytics.py`):
el panel y la respuesta del agente. No hay dos cálculos que puedan discrepar.

## Vencimientos y centro de alertas

Un vencimiento es un pago futuro con fecha (`Tarjeta Visa`, `Alquiler`,
`Seguro de la moto`), con monto, categoría de gasto y recurrencia
(`once` o `monthly`).

**El estado no se guarda: se deriva.** La tabla `bills` no tiene columna de
estado; sale de comparar `due_date` con hoy y de si tiene `paid_at`:
`pendiente` → `proximo` (7 días o menos) → `vencido`, o `pagado`.

Pagar un vencimiento hace tres cosas de una:

1. genera el movimiento de gasto (`Pago: <descripción>`),
2. marca el vencimiento como pagado,
3. si es mensual, crea el vencimiento del mes siguiente (misma fecha,
   cuidando el fin de mes: 31/01 → 28/02).

Por eso `pagar_vencimiento` **siempre pide confirmación**, sin importar el
monto: es una acción compuesta que escribe dinero real. Pagar dos veces se
rechaza con un 409.

El banner del Panel se alimenta de `GET /api/alerts` → `all_alerts()`, que
consolida en un solo lugar, de lo más urgente a lo menos:

- vencimientos vencidos (🔴) y próximos (🟡),
- presupuestos excedidos (🔴) y en atención (🟡),
- objetivos vencidos (🔴) y por vencer en 30 días (🟡),
- gastos fuera de lo habitual (🟡, resumidos en una línea).

El agente usa la misma función vía `listar_alertas`: lo que ves en el panel
es lo que te dice el chat. Preguntale *"¿qué tengo pendiente?"*.

## Modelo intercambiable (punto clave de la arquitectura)

Todo el sistema habla con `app/agent/provider.py`. Cambiar de modelo es editar
unas variables de entorno:

```bash
# NVIDIA API (la configuración usada en este laboratorio)
OPENAI_API_KEY=nvapi-...
OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1
OPENAI_MODEL=nvidia/nemotron-3-super-120b-a12b

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
│   ├── models.py          # Category, Transaction, SavingsGoal, Budget, Bill, Vehicle (centavos)
│   ├── schemas.py         # contratos Pydantic de la API
│   ├── analytics.py       # ← saldos, metas, presupuestos, vencimientos y alertas
│   ├── importer.py        # ← importar CSV + clasificador local (TF-IDF)
│   ├── api.py             # endpoints REST
│   ├── main.py            # app FastAPI + seed de categorías + guard de esquema
│   └── agent/
│       ├── provider.py    # ← capa de proveedor intercambiable
│       ├── agent.py       # bucle agente ↔ herramientas + confirmación
│       └── tools/         # 24 herramientas, una por módulo
│           ├── base.py            # formato de moneda + tipos comunes
│           ├── transactions.py    # movimientos + balance + resumen
│           ├── goals.py           # objetivos de ahorro
│           ├── budgets.py         # presupuestos mensuales
│           ├── vehicles.py        # vehículos (moto, auto)
│           ├── imports.py         # importar CSV + anomalías
│           └── bills.py           # vencimientos + centro de alertas
├── static/                # frontend (sin build step)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── scripts/
│   ├── demo.py            # datos de ejemplo (opcional)
│   ├── smoke.py           # regresión end-to-end (~55 chequeos)
│   └── prove_provider.py  # prueba real contra el proveedor configurado
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
  sigue vigente. La asimetría es deliberada: fijar *cuánto* querés ahorrar o
  *cuánto* gastar por categoría no mueve plata y no se confirma; mover plata
  (registrar una transacción) se confirma recién por encima de
  `SENSITIVE_AMOUNT`, borrar algo siempre se confirma, y pagar un vencimiento
  también (aunque sea chico: escribe un gasto real y puede crear el mes
  siguiente).
- **El balance de una meta se deriva, no se guarda**: no hay columna
  `saved_cents`. El progreso es la suma de los `transactions.amount_cents` que
  tienen esa `goal_id`. Un único libro contable, sin un contador que pueda
  desincronizarse del movimiento real. El cálculo vive en `analytics.py` para
  que la API (JSON) y las herramientas del agente (texto) no puedan discrepar.
- **Sin migraciones automáticas**: `create_all()` agrega tablas nuevas pero *no*
  columnas a tablas que ya existen. `main.py` compara el esquema esperado con el
  real al arrancar y corta con un mensaje accionable en vez de dejar que reviente
  un `no such column` a mitad de una consulta.
- **Un movimiento con `goal_id` también suma al balance general**: la plata
  efectivamente salió de la cuenta, además de contar para la meta. Está
  documentado en el prompt (regla 8) para que el modelo no lo cuente dos veces.
- **No se puede borrar una meta con aportes** (`409`): desvincularla en silencio
  dejaría movimientos de plata apuntando a la nada. Hay que deshacer el aporte o
  reasignar la meta primero.
- **El estado de un vencimiento también se deriva**: `pendiente` / `proximo` /
  `vencido` sale de `due_date` vs hoy, no de una columna. Y `pagar_vencimiento`
  siempre pide confirmación aunque el monto sea chico: genera un gasto real y
  (si es mensual) un registro futuro; es la misma razón por la que borrar
  siempre se confirma.
- **Un solo centro de alertas** (`all_alerts` en `analytics.py`): el banner del
  panel y `listar_alertas` del agente no pueden discrepar porque son la misma
  llamada con distinto formato (JSON vs texto).

## Roadmap

Hecho:

1. ✅ **Objetivos de ahorro** + separación de dinero por objetivo.
2. ✅ **Presupuesto mensual** por categoría con alertas (`ok` / `atención` /
   `excedido`, con proyección de ritmo a fin de mes).
3. ✅ **Gastos específicos de motos** (vehículos + tags por movimiento, ej:
   `Moto Honda` + `combustible`).
4. ✅ **Detección de gastos que se disparan** (vs media histórica por categoría).
5. ✅ **Alertas y tareas automáticas** (vencimientos únicos/mensuales con pago
   que genera el gasto, + centro de alertas unificado panel/agente).

Siguiente:

6. **Autenticación + multiusuario** (el paso a PostgreSQL y a "sistema para clientes").