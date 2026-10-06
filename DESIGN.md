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
- Motion: `rise` al entrar — 0.45s en los hijos del view con stagger 50ms, y
  también en la tarjeta de login y en el sheet del FAB (0.25s) — y `sheetup`
  al abrir el bottom sheet a 0.28s; todos sobre `--ease` = `cubic-bezier(.22,
  1,.36,1)` (ease-out exponencial). El esqueleto `.esq` late en loop a 1.5s
  con desfasaje de 180/360ms, para que el latido recorra los bloques en vez de
  parpadear todo junto. Todo lo demás son micro-transiciones de estado (hover,
  activo, foco) sobre `color`, `background`, `border-color`, `transform`,
  `opacity` y `box-shadow`.
  `prefers-reduced-motion` apaga animaciones y transiciones, y el esqueleto
  queda en `opacity:.55` fija: sin eso volvería a opacidad 1 y se leería como
  contenido cargado en vez de placeholder.
- Feedback de carga, en tres capas:
  - El panel completo pone `aria-busy` en `#main-container` mientras refresca
    (`refreshPanel` lo pone y lo saca; el CSS sólo le da cara visible): una
    barra fija de `--barra-alto` (3px) en menta corre arriba con `barra-carga`
    1.1s (scaleX 0→1 con fade al final), `z-index:90` — sobre el header, bajo
    el modal. Bajo reduced-motion queda una franja quieta al 55%, como el
    esqueleto.
  - El botón que dispara la acción inserta un anillo `.spin` ANTES de su
    texto desde `setBusy` (el texto ya no se cambia por "…": el botón sigue
    diciendo qué hace mientras trabaja). Mide `--spin` (1em, crece con el
    texto), usa `currentColor` (sirve en primario, ghost y danger) y gira
    0.7s. Bajo reduced-motion se oculta: alcanza con el botón disabled.
  - El movimiento recién registrado flashea su fila: `flashFila` la busca por
    `data-del` después de refrescar el panel y le pone `.feed-item.flash`,
    que anima `border-color` y `box-shadow` 0.9s (`cardflash`, las mismas
    propiedades que ya transiciona el resto de la app). Si la fila quedó
    fuera del período o de las 40 del límite, no hay nada que flashear y no
    pasa nada.
- Estados de presupuesto/objetivo/vencimiento: fondo con lavado del color del
  estado + barra que toma ese color; nunca texto rojo sobre rojo plano.
- Chips: categoría, objetivo (🎯 violeta suave), procedencia (💵 menta suave).
- Inputs y botones ≥46px de alto.

## Piso de craft (checks del detector)

- Sin halos de color (glow) en superficies: elevación con sombras neutras.
- Sin transiciones sobre propiedades de layout (`width`, `height`, `top`,
  `left`, `margin`, `padding`): las únicas que animan son `color`,
  `background`, `border-color`, `transform`, `opacity` y `box-shadow`.
- Contraste texto/fondo medido en 17:1; secundario ≥ 4.5:1.

## Reglas de no-regresión

- Cualquier superficie nueva usa este sistema; no introducir un segundo look.
- Las acciones sensibles siempre pasan por el pending-card ámbar del chat.
