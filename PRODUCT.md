# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Franco, uso personal diario desde el **celular** (la app corre en Vercel + Neon).
Cobra dinero por día de distintas procedencias y quiere el registro rápido y la
lectura clara del mes. En la compu durante el desarrollo; en el celu para operar.

## Product Purpose

Finanzas personales con agente de IA: registrar ingresos/gastos, presupuestos
mensuales con alertas, objetivos (ahorro / recaudación), vencimientos, y una
conversación con acciones confirmables. Éxito = saber cuánto entró, de dónde,
cómo vienen los presupuestos y qué vence, sin abrir una hoja de cálculo.

## Positioning

Un asistente financiero propio: datos del usuario, IA intercambiable
(NVIDIA/OpenAI/local), confirmación en el backend para acciones sensibles,
todo auditoría de un solo libro contable en centavos. Nadie más ofrece esa
combinación a costo ~cero y datos 100% del usuario.

## Operating Context

Flujo diario: cobrar → registrar ingreso con procedencia → mirar el Panel.
Mensual: presupuestos y rollover. Chat del agente para consultas rápidas.

## Capabilities and Constraints

- Multiusuario real (auth, aislamiento por `user_id`), SPA sin build step.
- Móvil primero: la escena real es pantalla chica, una mano, datos rápidos.
- API REST en FastAPI; el frontend sirve estáticos del mismo repo.
- Montos en centavos (enteros), formato es-AR.
- Idioma: español (voseo argentino en textos).

## Brand Commitments

Nombre: "Finanzas Personales" con emoji 💰. Dirección visual elegida por el
usuario para el rediseño: **neo-bank oscuro** (Revolut/Ualá): dark mode
premium, números protagonistas. Pantalla priorizada: **Panel** (home diaria).

## Product Principles

1. El celular es la escena real: un gesto para lo frecuente.
2. Los números mandan: jerarquía por datos, no por decoración.
3. Nada mueve plata sin confirmación visible.
4. Ver estados malos de un vistazo (presupuesto al límite, vencimiento rojo).
5. Simple de mantener: un solo archivo de estilos, sin build step.
