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

Es **reentrante**: al arrancar borra lo que quedó de una corrida anterior
(interrumpida, por ejemplo), así que se lo puede cortar y volver a correr sin que
la siguiente muera en un 409 por nombre repetido.

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
| `listar_billeteras` | Billeteras con su saldo derivado y el patrimonio total | No |
| `crear_billetera` | Da de alta una billetera con el saldo real que tiene hoy | **Siempre** (fija de qué plata habla) |
| `ajustar_saldo_billetera` | Conciliación: el saldo derivado pasa a ser el número real declarado | **Siempre** (reescribe el saldo) |
| `eliminar_billetera` | Borra la billetera; sus movimientos pasan a «General» | **Siempre** |
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

## Billeteras y patrimonio

Una billetera es una cuenta real (Mercado Pago, el banco, efectivo). El Panel
muestra el **patrimonio total** arriba y el detalle por billetera abajo.

**El saldo de una billetera no se guarda: se deriva.** Es
`apertura_cents + Σ movimientos`, igual que el saldo de un objetivo se deriva de
sus aportes. El único número que se declara a mano es la apertura (el saldo real
que tiene la billetera hoy); de ahí en adelante se mueve sola con cada
movimiento que le cargues. Con varias billeteras, un snapshot manual se desactualiza
en semanas y el total miente: esto no tiene un segundo número que pueda mentir.

"Ajustar saldo" es una **conciliación**, no una corrección: mandás el número que
figura hoy en la app del banco y el backend rebasa la apertura para que el
derivado dé exactamente ese número. No borra movimientos ni inventa los que
faltaban.

Cada movimiento tiene que caer en una billetera. Si el movimiento no dice
cuál, el backend lo imputa a **«General»**, una billetera que existe siempre por
usuario: el patrimonio no puede perder plata porque te olvidaste de elegir.
«General» no se puede borrar ni renombrar, y en la interfaz no muestra botones
de ajuste — es un destino automático, no una cuenta que declares.

En la fila de cada billetera hay un solo botón (ajustar saldo). Borrar vive
dentro de esa misma hoja: en un teléfono de 360px una fila con dos botones deja
el nombre ilegible, y borrar una billetera amerita que ya hayas abierto esa
billetera.

## Dinero comprometido y disponible real

El patrimonio dice cuánta plata tenés. No dice **cuánta ya te la gastaste en
compromisos**, y esa diferencia es la que importa antes de gastar.

`GET /api/summary` agrega tres números que salen de la misma función
(`comprometido()` en `app/analytics.py`, sobre `bill_rows()`):

- `comprometido_cents` — todo lo impago, vencido o futuro. El total que ya no
  es tuyo aunque todavía esté en la cuenta.
- `comprometido_mes_cents` — lo que vence este mes calendario.
- `vencido_cents` — lo que ya pasó de fecha sin pagarse (el urgente).
- `disponible_cents` — `patrimonio − comprometido`. El único número que
  contesta "¿puedo gastar esto?".

Los montos van acompañados de `comprometido_count` y `vencido_count` porque
450.000 comprometidos son una cosa si es un pago y otra si son cinco.

Dos decisiones que conviene no romper:

- **El disponible se calcula una sola vez, en el backend.** Si el panel lo
  restara por su cuenta y el agente también, un día divergen. Es el mismo
  argumento que sostiene el saldo derivado de las billeteras.
- **Estas cifras ignoran `desde`/`hasta` a propósito.** El resto de
  `/api/summary` es un período, pero un vencimiento no "es de este mes": vence
  en una fecha. Filtrar el resumen por fechas no puede moverlas, y el smoke lo
  verifica.

El hero de Inicio muestra el resultado del período (un flujo: lo que entró
menos lo que gastaste) separado del disponible real (un stock), con la línea de
comprometido debajo. La etiqueta pasó de "Balance del período" a "Resultado del
período" a propósito: "balance" mezclaba las dos cosas y se leía como "tengo
esta plata".

El agente lo dice en la misma línea de `calcular_balance`: sin ella comparaba un
gasto contra un número que todavía había que pagar.

## Cómo está organizada la app (IA)

Cinco destinos: **Inicio, Movimientos, Metas, Agente, Más**. La regla que los
ordena es una sola: *lo que se consulta todos los días va arriba, lo que se mira
una vez al mes baja*.

**Inicio** responde una pregunta —"¿cómo estoy?"— y por eso tiene las cuatro
cosas que se miran sin decidir nada, en este orden:

1. El hero (resultado del período + disponible real).
2. Pagos que tenés que hacer — con tope de 3 filas y "ver los N más".
3. Presupuesto del mes, en modo consulta: **sin** botón de eliminar.
4. Gastos por categoría.
5. Billeteras.

Tres decisiones que conviene no romper:

- **"Gastos por categoría" se queda en Inicio.** Ilevarlo a Más dejaba a Inicio
  sin contestar "¿en qué se me va la plata?", que es una pregunta diaria.
- **El presupuesto aparece en Inicio sin el ✕.** Borrar un presupuesto desde la
  pantalla donde lo estás mirando es destructivo fuera de contexto: el
  borrado vive en Metas. Las dos pantallas comparten `budgetRowHtml(b, conBorrar)`
  en `static/app.js`, así el texto, el ícono y la barra se escriben una sola vez
  y no pueden mostrar números distintos.
- **El selector de período se fue a Movimientos** (el patrimonio es un punto en
  el tiempo, no un período), pero el hero también depende de él. Por eso el hero
  muestra el período que está usando: si no, el número de Inicio cambiaría en
  silencio desde otra pantalla.

La lista de pagos se corta en 3 filas porque la card tiene que responder "¿qué
pago ahora?" de un vistazo. Con 8 vencimientos, el scroll hasta "Gastos por
categoría" era de tres pantallas. "Ver los N más" los muestra igual, en el
lugar: nada queda escondido sin salida.

**Nada se borró.** Las tres cards chicas (ingresos, gastos, movimientos) y la
card "Ingresos del mes" se movieron a **Más**; el feed se movió a
**Movimientos**. Las ocho funciones de render de `static/app.js` siguen igual.

### La barra de destinos

En el teléfono, los cinco destinos viven en una barra fija abajo
(`#main-tabbar`), no en el header. Con cinco pestañas arriba, la nav se comía
media pantalla y el contenido empezaba en el pliegue; abajo queda al alcance del
pulgar y siempre visible. En escritorio (≥521px) la barra se oculta y sigue
mandando la nav del header, que es donde se la espera.

Las dos navegaciones comparten `data-view` y ninguna tiene estado propio: el
handler es `showView(view)` en `static/app.js`, que marca el destino en **todas**
las navs que lo tienen. Por eso no pueden desincronizarse.

Dos detalles de la barra:

- El botón de agregar **no** va en la barra. Es el FAB, que flota 75px arriba de
  ella (`bottom: calc(75px + env(safe-area-inset-bottom))`). Si se apoyara en el
  borde de la pantalla taparía la última etiqueta.
- `.container` reserva `padding-bottom: calc(152px + env(safe-area-inset-bottom))`
  en móvil: los 96px base cubrían el FAB solo, no el FAB más la barra.

`initTabs()` se ata a `[data-view]` y no a `.tab`. Antes se ataba a toda clase
`.tab`, incluidas las pestañas del login y el botón "Salir", que no tienen
`data-view`: un click ahí corría la vista con `undefined` y tapaba todas las
secciones. No se notaba porque "Salir" además cierra sesión.

## Usuarios y autenticación

Cada usuario ve **solo sus datos**: registro con `POST /api/auth/register`
(devuelve un token), login con `POST /api/auth/login`, y el resto de los
endpoints exige `Authorization: Bearer <token>` (sin token → 401).

Detalles deliberados:

- Contraseñas con PBKDF2-SHA256 de la stdlib (sin dependencias nuevas) y
  sesiones como tokens opacos **revocables** (`POST /api/auth/logout`).
  En la base solo hay hashes, nunca secretos en claro.
- El login devuelve el mismo 401 exista o no el usuario: no filtramos quién
  está registrado.
- Borrar o leer un ID ajeno devuelve **404, no 403**: ni siquiera se confirma
  que ese registro exista.
- Las categorías son por usuario (mismo set inicial, después divergen).
- El agente opera siempre como el usuario del token: categorías del prompt,
  queries y clasificador CSV están scopeados por `user_id`.

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
│   ├── models.py          # User, Category, Transaction, SavingsGoal, Budget, Bill, Vehicle, Account (centavos)
│   ├── auth.py            # hashing PBKDF2 + tokens opacos (stdlib, sin deps)
│   ├── seed.py            # categorías iniciales por usuario
│   ├── schemas.py         # contratos Pydantic de la API
│   ├── analytics.py       # ← saldos, metas, presupuestos, vencimientos y alertas
│   ├── importer.py        # ← importar CSV + clasificador local (TF-IDF)
│   ├── api.py             # endpoints REST
│   ├── main.py            # app FastAPI + seed de categorías + guard de esquema
│   └── agent/
│       ├── provider.py    # ← capa de proveedor intercambiable
│       ├── agent.py       # bucle agente ↔ herramientas + confirmación
│       └── tools/         # 28 herramientas, una por módulo
│           ├── base.py            # formato de moneda + tipos comunes
│           ├── transactions.py    # movimientos + balance + resumen
│           ├── goals.py           # objetivos de ahorro
│           ├── budgets.py         # presupuestos mensuales
│           ├── vehicles.py        # vehículos (moto, auto)
│           ├── imports.py         # importar CSV + anomalías
│           ├── accounts.py        # billeteras + patrimonio
│           └── bills.py           # vencimientos + centro de alertas
├── static/                # frontend (sin build step)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── scripts/
│   ├── demo.py            # datos de ejemplo (opcional)
│   ├── smoke.py           # regresión end-to-end (104 chequeos, incluye auth y aislamiento)
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
- **Aislamiento por `user_id`, no por convención**: toda tabla de dominio
  tiene `user_id` con borrado en cascada, y los lookups por ID verifican dueño
  (`_owned`: 404 si no es tuyo). Un `WHERE` olvidado es un leak, así que el
  smoke tiene checks de aislamiento A-vs-B en API y en agente.
- **SQLite por defecto, PostgreSQL cambiando la URL**: verificado de punta a
  punta (smoke completo en verde) contra PostgreSQL 16 local con
  `DATABASE_URL=postgresql+psycopg://...`. El driver es `psycopg[binary]`.
- **Sesiones sin JWT**: un token opaco en `user_sessions` alcanza y sobra para
  este tamaño; se revoca con un DELETE en vez de manejar expiraciones y
  refresh tokens. Si algún día hay app móvil con "recordarme", ahí sí JWT.

## Deploy en Vercel (para usarla en el celular)

Vercel ejecuta la app como función serverless y **no tiene disco persistente**:
SQLite ahí pierde los datos entre invocaciones. Por eso el deploy usa
PostgreSQL manejado (Neon, gratis) y Vercel solo corre el código. El repo ya
viene listo: Vercel detecta solo el entrypoint `app/main.py` (cero config de
rutas; las de `/api/*` ganan al mount estático porque el router se declara
antes) y `vercel.json` le da 60s a la función (el agente a veces tarda).

Pasos (una sola vez):

1. **Base de datos** en [Neon](https://neon.tech) (tier gratis): creá un
   proyecto y una base `finanzas`. Copiá la **pooled connection string**
   (termina en `-pooler...`) y agregale `?sslmode=require`:
   `postgresql+psycopg://<user>:<pass>@<host-pooler>/finanzas?sslmode=require`
2. **Repo en GitHub**: `gh repo create finanzas --private --source=. --push`
   (o crealo en la web y `git remote add origin ... && git push -u origin main`).
3. **Proyecto en Vercel**: importá el repo. Variables de entorno (Settings →
   Environment Variables, marcar Production):
   - `DATABASE_URL` = la de Neon de arriba (las tablas se crean solas al arrancar)
   - `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` = las de tu `.env`
   - `SENSITIVE_AMOUNT`, `BUDGET_ALERT_PCT`, `CURRENCY` = igual que tu `.env`
4. **Deploy** y abrí la URL en el celular → *Agregar a pantalla de inicio*
   (el `manifest.json` hace que abra a pantalla completa).

Notas:

- Sin `DATABASE_URL` la app igual arranca pero **pierde los datos**: no usar
  SQLite en Vercel salvo para probar.
- Primer paso en la app deployada: crear tu cuenta (cada usuario ve solo lo suyo).
- El plan Hobby de Vercel duerme la función sin tráfico: la primera carga
  tarda unos segundos (cold start + lifespan). Después vuela.

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
6. ✅ **Autenticación + multiusuario** (usuarios con token, aislamiento total
   por `user_id`, categorías por usuario, verificado en SQLite y PostgreSQL).
7. ✅ **Procedencia de los ingresos** (`source`): cargás el cobro con su origen
   y el mes se desglosa por fuente, no solo por total.
8. ✅ **Objetivos de dos tipos**: `ahorro` (juntás hasta X) y `recaudación`
   (ahorrás netamente para un fin, gastando en el camino).
9. ✅ **Billeteras + patrimonio** (saldo derivado por billetera, conciliación,
   «General» como destino de lo que no se imputa, agente con 4 herramientas).

Roadmap completo. Posibles siguientes (no definidos): app móvil / PWA con
login persistente, rate-limit al login, expiración de sesiones, roles
(admin), exportar/importar por usuario.