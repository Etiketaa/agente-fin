# Design system — Finanzas Personales

<!-- Sistema actual (neo-bank oscuro, elegido por el usuario 2026-10-02).
   Reemplaza al mundo claro inicial. Autoridad: static/styles.css. -->

## Mundo

Billetera abierta de noche. El balance es la escena; lo demás es soporte.
Operate-mode, celular primero, una mano, lectura en segundos.

## Color

| Rol | Valor | Uso |
|---|---|---|
| Fondo | `#0b0e12` | página |
| Elevado | `#13181f` / `#12171f` | cards |
| Borde | `rgba(255,255,255,.07)` | cabello fino |
| Texto | `#eef2f6` | contenido |
| Apagado | `#9aa7b4` | texto secundario (tinte azulado, no gris) |
| Menta | `#34e0a1` | acento, acción primaria, estado ok |
| Ingreso | `#3fe0a5` | plata que entra |
| Gasto | `#ff7a6e` | plata que sale / vencido / excedido |
| Ámbar | `#ffc24b` | atención, próximo, confirmaciones |

## Tipografía

Manrope (500/600/700/800, Google Fonts con preconnect; fallback system stack).
`tabular-nums` global. Display 800 con tracking -0.02/-0.03em para el balance.

## Composición y estados

- Header sticky con blur, tabs en píldora; la activa es menta con tinta oscura.
- Hero card: balance en `clamp(2rem, 6vw, 2.9rem)`, lavado diagonal menta.
- Motion: un solo gesto (`rise` en los hijos del view, stagger 50ms), ease-out
  exponencial; sin otros efectos. `prefers-reduced-motion` desactiva todo.
- Estados de presupuesto/objetivo/vencimiento: fondo con lavado del color del
  estado + barra que toma ese color; nunca texto rojo sobre rojo plano.
- Chips: categoría, objetivo (🎯 violeta suave), procedencia (💵 menta suave).
- Inputs y botones ≥46px de alto.

## Piso de craft (checks del detector)

- Sin halos de color (glow) en superficies: elevación con sombras neutras.
- Sin transiciones que animen `width` (layout); el único movimiento es `rise`.
- Contraste texto/fondo medido en 17:1; secundario ≥ 4.5:1.

## Reglas de no-regresión

- Cualquier superficie nueva usa este sistema; no introducir un segundo look.
- Las acciones sensibles siempre pasan por el pending-card ámbar del chat.
