---
target: la SPA completa de Finanzas Personales, todas las vistas, mobile-first
total_score: 18
max_score: 40
na_heuristics: 
p0_count: 2
p1_count: 10
target_identity: "file:/home/franco/finanzas/static/index.html"
target_fingerprint: "sha256:521d4ee343e945cd47dba03df7fa460f0ce61515e3f3f436646e543f20756af9"
target_path: /home/franco/finanzas/static/index.html
timestamp: 2026-10-06T04-46-25Z
slug: static-index-html
---
# Critique — `static/index.html` (Finanzas Personales SPA)

> ## Verificación posterior — Franco, 2026-10-06
>
> Auditoría hecha por `impeccable` y leída contra el código real **después**. Los números
> de esta nota son míos, los verifiqué con `grep` y `read` sobre los archivos, no con la
> herramienta. Los de arriba (`total_score: 18`, `p0_count: 2`, `p1_count: 10`) son los que
> reportó ella y los dejo intactos: es lo que midió, aunque tres de sus severidades no se
> sostienen.
>
> **No resistieron la verificación:**
>
> 1. **P0 #1 — "sin `aria-busy`" es falso.** El atributo se pone en `#main-container`
>    (`app.js:675`) y se saca al terminar (`app.js:690`). Lo que sí es cierto, y baja a P1,
>    es que el hero no está en `ESQUELOTOS` (`app.js:647`, 8 contenedores): sus dos números
>    arrancan como `—` (`index.html:153,155`) y el resto del panel tiene esqueleto.
>
> 2. **P0 #2 — "archivado en silencio" es falso.** `marcarChip` marca el chip de la primera
>    categoría del `kind` (`app.js:174`), y el chip queda visible con `.active` y
>    `aria-checked="true"`. Después, la categoría aparece en el feed en
>    `app.js:559` (`feed-sub muted small`). No es un silencio: es un *default* que adivina
>    («Comida», por orden alfabético). Eso es P2, no P0.
>
> 3. **P1 #4 — "ningún target táctil llega a 44px" es falso.** `.btn` tiene
>    `min-height: 46px` (`styles.css:423`) y lo mismo otro en `styles.css:203`.
>    Lo real es que `.chip`, `.btn.ghost` y `.small-btn` están en **38px**
>    (`styles.css:383,431,434`): faltan 6px.
>
> **Lo que sí está medido bien:**
>
> - `--fs-2xs: 0.66rem` = **10.56px exacto** (`styles.css:40`), y se usa en las etiquetas
>   del tabbar (`styles.css:533` y `894`). Confirmado al valor.
> - El contraste de `hero-period` y `hero-sep` (3.98:1) no lo recalculé, pero los dos P0
>   erraron el suyo, así que conviene recomputarlo antes de tocar el color.
> - El `theme_color`/`background_color` mentiroso del manifest lo confirmé por mi cuenta en
>   otra revisión (Fase 11 pendiente): `#f4f6f8` contra `--bg: #0b0e12`.
>
> **Cómo se usa este archivo:** sirve de *lista de qué mirar*, no de *severidad*. Los P1 y
> P2 son el material útil; los dos P0, al menos, no.

Run degradado: single-context (no sub-agent tool exposed — session is already at subagent depth 1).
Assessment A fue registrada completa ANTES de que existiera salida del detector.
Degradaciones adicionales: no puedo leer imagenes (capturas hechas, no inspeccionables) — todos los
juicios visuales estan fundamentados en geometria/DOM medidos. `impeccable live-server` no existe
en el CLI (solo detect/ignores/help/install/link/update/check), asi que no hubo inyeccion de overlays
en vivo; la mitad browser de Assessment B se sustituyo por medicion directa en Chromium.

Superficie: static/index.html (573 lineas) + styles.css (1131) + app.js. 5 vistas x 4 anchos
(375x667, 768, 1024, 1440) + 3 sheets + fab-sheet. App real servida en 127.0.0.1:8000, usuario
`demo` sembrado, login por la API real. 217 KB en 16 requests, 0 errores de consola.

## Veredicto de especificidad

Autorado, no prestado — pero autorado para el dashboard de escritorio y despues retrofitteado al
telefono. Decisiones no genericas y explicadas en el CSS: `.dot` reemplazando emoji de estado
("un estado que cambia de forma no es un estado"), sprite SVG inline para que ningun origen falle,
`env(safe-area-inset-bottom)` en el tabbar, reflow de `.goal-desglose` a 400px, regla `.feed-del`
con `@media (hover:none)`.

Donde deja de ser especifico de este producto: el Panel es una pila de cinco cards con borde y un
hero — la pila neo-bank generica. El contrato de `.impeccable/surfaces/static-index-html.md` promete
lo contrario ("debajo del banner de alertas la lista 'Movimientos' de alto contraste... Registrar
sigue un tap mas abajo"). El Panel construido NO tiene feed; la lista vive en otra pestana. Las dos
cosas que una app de finanzas personales sabe y un dashboard no ("es la 5ta vez que compras super",
"tenes tres tarjetas autopagando") no estan en el primer viewport.

## Heuristicas (Operate: 7 y 10 aplican, ninguno n/a)

| # | Heuristica | Score | Hallazgo |
|---|---|---|---|
| 1 | Visibilidad del estado | 1 | Hero muestra `—` ~6s: t=0.5s `—`, 1.5s `—`, 3s `—`, 6s `-$ 30.000,00`. 10/10 llamadas 200. Sin skeleton en el hero aunque `.esq` existe para las cards de abajo. |
| 2 | Match sistema / mundo real | 2 | ISO crudo en UI premium: `· 2026-10-01 → 2026-10-06` a 11.84px. Dos lineas mas abajo el app humaniza `dom, 4 oct`. |
| 3 | Control y libertad | 2 | `closeSheets()` (app.js:1373) NO restaura foco: no hay tracking del opener. Verificado midiendo: el foco aterriza donde caiga por orden del DOM. Sin undo al borrar. |
| 4 | Consistencia y estandares | 2 | El selector de periodo vive en Movimientos pero maneja el hero en Panel; el codigo compensa con nota al pie en vez de locolocar. |
| 5 | Prevencion de errores | 1 | `markarChip(hidden, propias[0]?.name)` preselecciona "Comida". Monto + "Registrar gasto" = dinero en el balde equivocado sin confirmacion. |
| 6 | Reconocer sobre recordar | 3 | Chips en vez de `<select>` nativo; headers de dia humanizados; FAB con 4 acciones etiquetadas. |
| 7 | Flexibilidad y eficiencia | 2 | FAB + tabbar es rapido, pero la 4ta pestana es "Mas" con tres tiles. |
| 8 | Diseno estetico y minimalista | 2 | Fold 375x667: hero → card Pagos vacia → "Presupuesto del mes" → parrafo de 56px → primera fila real en y=661, un pixel pasado el pliegue. 2 de 4 cards son empty states. |
| 9 | Recuperacion de errores | 2 | Empty states bien escritos. Errores a un toast de 3.2s — y no hay NINGUNA region `aria-live` en la app. |
| 10 | Ayuda y documentacion | 1 | Los 6 prompts del Agente renderizan en y=638–731, bajo el pliegue de 667px. |
| **Total** | | **18/40** | **Poor — requiere trabajo UX mayor** |

## Carga cognitiva — 5 de 8 fallan

- [ ] Foco unico — FAIL. El Panel hace cinco preguntas en un scroll (index.html:141-144). En 667px solo la primera es contestable arriba del pliegue.
- [ ] Chunking — FAIL. Una columna de 1818px en pantalla de 667px (2.7 pantallas).
- [x] Agrupamiento — pass.
- [ ] Jerarquia visual — FAIL. `h1` computa a 16px, identico a cada `h2`.
- [x] Una cosa a la vez — pass.
- [ ] Elecciones minimas — FAIL. 10 chips de golpe, planos, sin scroller (medido: 10 `.chip`, todos 38px). Cowan ~4.
- [ ] Memoria de trabajo — FAIL. `#tx-category` es input oculto; lo elegido existe solo como outline menta.
- [x] Descubrimiento progresivo — pass.

## Recorrido emocional

- Valle (P1, medido): los 6s despues del login con el hero en `—`. La primera pregunta emocional del usuario es "¿cuanto tengo?" y la app contesta con un guion medio.
- Valle (P1): Agente = 340px de `min-height` vacio + banner de desarrollador con `OPENAI_API_KEY` literal.
- Reafirmacion (bien): `.pending-card`, wash ambar, "Se requiere tu confirmacion", Si/No explicito. El ritual correcto para dinero y el mejor momento de la app.
- Pico perdido (P1): nada celebra un movimiento registrado mas alla de un toast de 3.2s.
- Fin: el dia cierra sin cierre; no hay "hoy te faltan X" ni confirmacion de que los libros balancean.

## Thumb reach a 375x667 — genuinamente bueno

- Centro del FAB en y=563/667, zona del pulgar, 58x58.
- Tabbar en top 611, h=56, alcance inferior.
- `+ Agregar` vencimientos en y=333 (medio), billeteras en y=719 (bajo pliegue) — correcto para tarea dos veces por mes.
- Cromo persistente = header 60 + tabbar 56 = 116px de 667 = 17.4%.

## Evidencia del detector (verificada una por una)

`impeccable detect --json static/index.html` → exit 2, 18 hallazgos.

| Regla | Cant. | Veredicto |
|---|---|---|
| `cramped-padding` | 12 | FALSO POSITIVO, las 12 |
| `undersized-ui-text` | 5 | CONFIRMADO, las 5 |
| `em-dash-overuse` | 1 | Advisory estetico, no es defecto |

Las 12 `cramped-padding` son falsos positivos: el detector leyo el HTML sin CSS. En realidad
`styles.css:224` es `padding: 20px max(var(--space), 18px)`; a 375px `--space` = 15px, luego
`max(15,18)` = 18px de inset horizontal. Ademas NINGUNA variante de `.card` overridea el padding
(`grep -nE "\.card[^{]*\{[^}]*padding"` → 0 resultados). Piso del detector 8px, real 18px.

Las 5 `undersized-ui-text` son reales: 10.56px en las 5 etiquetas del tabbar (`--fs-2xs: 0.66rem`,
styles.css:40). Medido en navegador: 10.56px a `span.tabbar-label`. El mismo token lo usan los
`.tag`, así que el problema es del token.

## Contraste — 40 de 42 estilos de texto pasan

Medidos todos los nodos de texto renderizados, 5 vistas x 4 anchos, compositando el fondo real.

| Ratio | Tamano | Que |
|---|---|---|
| 3.98 FALLA | 11.84px | `span#hero-period` — `· 2026-10-01 → 2026-10-06` |
| 3.98 FALLA | 14.08px | `span.hero-sep` — `·` |
| 7.07 | 27–46px | `--expense` en el hero |
| 7.27–7.33 | 11.8–14.7px | `--muted`, `.card-label`, `.muted.small` |
| 7.88 | 10.56–14.1px | `.tabbar-label` inactivo, `#logout-btn` |
| 8.68 | 13.1–27.2px | texto sobre `--mint-ink` |
| 10.5–17.2 | 10.6–33.6px | `--mint`, `--income`, `--text` |

Solo falla `--faint #6b7885` (3.98:1), y solo en dos elementos del hero, 20 ocurrencias cada uno.

## Targets tactiles — fallan en TODOS los anchos

| Elemento | Medido | Anchos |
|---|---|---|
| `#logout-btn` "Salir" | 53x35 | los 4 |
| `#btn-nuevo-bill` / `#btn-nueva-cuenta` "+ Agregar" | 90x38 | los 4 |
| `✕ Cerrar` (`.small-btn`) en cada sheet | 82x38 | 3 sheets x 4 anchos |
| Los 10 chips de categoria | 56–97x38 | los 4 |
| `.seg-btn` Gasto/Ingreso | 165x40 | los 4 |
| `.tabs .tab` nav escritorio | 56–114x40 | 768/1024/1440 |
| `#tx-more-toggle` "Mas opciones" | 343x35 | los 4 |

NINGUN elemento interactivo de la app llega a 44px de alto.

## Reflow a 200%

| Viewport | Desbordamiento horizontal |
|---|---|
| 375 | +494px (scrollWidth 869) |
| 768 | +122px |
| 1024 | 0 |
| 1440 | 0 |

WCAG 1.4.10 roto a 375 y 768, incluido el dispositivo objetivo.

## Accesibilidad runtime

- `role="radiogroup"` con 10 radios y CERO soporte de flechas: con foco en "Comida", ArrowRight x2 y
  ArrowDown no mueven foco ni seleccion. Las 5, 5 veces. Los 10 chips son paradas de Tab separadas
  (medido: paradas 1–10 = Comida→Compras→Educacion→Motos→Ocio→Otros→Salud→Servicios→Transporte→Vivienda).
- Fuga de foco: `sheet-movimiento` abierto escapa en la parada #13; `sheet-bill` en la parada #9.
- Los 3 sheets: `aria-modal` = null, `inert` = false, en los 4 anchos (index.html:391, 453, 489).
- `closeSheets()` no restaura foco (app.js:1373-1379, solo saca `.hidden`). En el path del FAB cae en
  `#fab` por casualidad; en el path de `#btn-nuevo-bill` cae en `#btn-nueva-cuenta`, el boton equivocado.
- 0 regiones `aria-live` en toda la app: el toast no se anuncia y la carga del hero tampoco.
- Orden de Tab roto a 375: el nav es `display:none` a <=520px y sale del orden, pero `#logout-btn`
  (misma clase `.tab`) se queda. El foco arranca en `+ Agregar` (y=333).
- Bien: 0 inputs sin etiqueta, 0 img sin alt (no hay `<img>`, todo SVG inline), 0 botones sin nombre
  accesible, landmarks presentes (header/nav/main/nav), `*:focus-visible` global con outline de 2px.
- `h1` = 16px = todos los `h2`.

## Movimiento, theming, performance

- `prefers-reduced-motion` existe pero el primer bloque es `* { animation: none !important; transition: none !important; }`.
  Medido con `reducedMotion:'reduce'`: `cardAnimationName: "none"`, `cardTransition: "0s"`, `fabTransition: "0s"`.
  Se pierde todo el feedback de cambio de estado, incluido el flash de `.pending-card`.
  El segundo bloque rescata el shimmer de skeletons con `opacity: 0.55` estatico.
- Sin abuso de `will-change`. Cero transiciones de propiedades de layout (solo transform/opacity).
- Solo 5 hex literales fuera de `:root`, 3 funcionales. Pero `violet` es un TOKEN FANTASMA:
  `#bb9dff` y `rgba(174,149,255,.14)` hard-codeados en styles.css:541 y :1086, sin `--violet` en `:root`.
- `manifest.json` `theme_color: #0f172a` vs `--bg: #0b0e12`.
- Peso 221.789 bytes en 16 requests. `app.js` 112 KB monolitico, `styles.css` 77 KB, cero imagenes,
  10 llamadas `/api/*` al login. `backdrop-filter: blur(14px)` header + `blur(16px)` tabbar +
  dos gradientes radiales en `body` → compositing caro en Android de gama baja.

## Veredicto de integridad de implementacion

PASA. La implementacion expresa un sistema coherente y especifico del producto, demostrado en el
codigo: el razonamiento del sprite inline, del `.dot`, del `@media (hover:none)` y de los
safe-area esta escrito en los comentarios. Los 12 falsos positivos del detector son culpa del
detector. Pero hay un error silencioso de datos en la accion mas frecuente, un estado de carga de
6s sin skeleton, 35 lineas de CSS muerto, un token fantasma, y el build contradiciendo el contrato
de su propia surface brief.

| # | Dimension | Score | Hallazgo clave |
|---|---|---|---|
| 1 | Accesibilidad | 2/4 | radiogroup con 10 paradas de Tab y cero flechas; dialogos sin aria-modal/inert/trap; 0 regiones aria-live |
| 2 | Performance | 3/4 | 217 KB sin imagenes y motion solo en transform/opacity, pero 10 llamadas al login causan el blank de 6s |
| 3 | Responsive | 2/4 | Reflow a 200% desborda 494px a 375; ningun target llega a 44px |
| 4 | Theming | 3/4 | 5 hex sueltos de 1131 lineas, pero `violet` no existe como token |
| 5 | Integridad | 2/4 | Un error silencioso de datos + CSS muerto + token fantasma |
| **Total** | | **12/20** | **Acceptable — requiere trabajo significativo** |

27 hallazgos: 2 P0, 10 P1, 10 P2, 5 P3.

## Issues por prioridad

### P0
1. **El hero responde la pregunta del dia con `—` durante ~6 segundos.** Sin skeleton propio, sin
   `aria-busy`, sin `role="status"`. El guion medio significa "sin valor", no "cargando".
2. **Un gasto queda archivado en silencio bajo "Comida".** `markarChip(hidden, propias[0]?.name)`.
   Violacion directa del principio 3 de PRODUCT.md.

### P1
3. Reflow roto a 200% (+494px a 375). WCAG 1.4.10.
4. Ningun target tactil llega a 44px. 7 familias, los 4 anchos. WCAG 2.5.5 / 2.5.8.
5. Dialogos sin `aria-modal`, sin `inert`, sin trampa de foco, sin restauracion de foco.
6. `role="radiogroup"` sin flechas y con 10 paradas de Tab.
7. Cero regiones `aria-live`: toasts y carga no se anuncian. WCAG 4.1.3.
8. Primer viewport sin datos accionables: primera fila de presupuesto en y=661.
9. Descubrimiento del Agente bajo el pliegue (y=638–731) y banner con copy de desarrollador.
10. Contraste 3.98:1 en `hero-period` y `hero-sep`. WCAG 1.4.3.
11. `--fs-2xs` = 10.56px en las 5 etiquetas del tabbar.
12. Orden de Tab roto a 375 (nav display:none vs `#logout-btn`).

### P2
13. `h1` = 16px = `h2`.
14. Dos botones con el mismo nombre accesible "+ Agregar". WCAG 2.5.3.
15. ISO crudo junto a headers humanizados.
16. Tras "Mas opciones" el submit queda en y=968, 301px bajo el pliegue, 6 de 10 campos abajo, sin senal de scroll.
17. "Movim." como etiqueta.
18. Kill global de reduced-motion destruye todo feedback de estado.
19. Token `violet` fantasma.
20. 2px de desborde horizontal en Agente a 375.
21. `theme_color` del manifest no coincide.
22. `black-translucent` sin `env(safe-area-inset-top)`.

### P3
23. CSS muerto: `.qa-row`/`.qa` (447–481), `.table-wrap`, `.grid`.
24. Nota al pie de `hero-period`.
25. Advisory de em-dashes.
26. `backdrop-filter` en gama baja.
27. `app.js` monolitico de 112 KB.

## Lo que esta bien — mantener y replicar

Contraste del sistema de color (40 de 42 estilos en 7:1–17:1, con "tinte azulado sobre oscuro, no
gris neutro"). FAB en y=563, centro exacto de la zona del pulgar. `env(safe-area-inset-bottom)` en el
tabbar. Sprite SVG inline. `@media (hover:none)` que sube `.feed-del` a `opacity:1` — alguien penso
en el dedo antes que en el mouse. `.pending-card` como ritual de confirmacion de dinero. `.dot` en
lugar de emoji. Cero `<img>`, cero frameworks, cero layout thrash, transform/opacity unicamente,
motion con `clamp()` en tokens fluidos.

## Preguntas provocativas

- El brief prometia un feed en el Panel y el build no lo tiene. Cual es la verdad: queres un feed en el Panel o el brief era aspiracional? Todo lo demas del primer viewport depende de la respuesta.
- Si "Disponible real" es el numero que realmente consultás, por que es el segundo y no el unico? Dos numeros grandes en una card es una jerarquia que el usuario tiene que aprender.
- Que veria la app si el blank de 6 segundos fuera el enemigo y cada superficie tuviera que responder su pregunta en menos de un segundo desde cache?
- Diez chips planos es un patron de escritorio reducido. Sentiria mas natural una tira con snap-scroll horizontal de las 5 categorias mas usadas, con el resto a un tap?
- El diferenciador de la app es un agente de IA que actua. Ahora su superficie de descubrimiento esta bajo el pliegue y su banner de fallback es copy de desarrollador. Se esta lanzando el agente o se lo esta escondiendo?
