---
version: 1
slug: "static-index-html"
primary_target: "static/index.html"
related_targets: ["static/styles.css","static/app.js"]
---

# Surface brief — Panel (home)

Modo: **Operate**. Escena real: celular, una mano, luz ambiente mixta
(calle/transporte/casa) — el usuario mira saldo y estados en segundos.
Dark elegido por scene + dirección pinned "neo-bank oscuro".

Audiencia: Franco; tarea diaria: saber cuánto hay, qué vence, qué pasó hoy;
acción frecuente: registrar cobro/gasto.

## Direction contract

THESIS: El Panel es una billetera abierta de noche: la plata disponible es la
escena; todo lo demás es soporte. Rechaza el dashboard neutro por ordenado.
OWN-WORLD: tinta profunda (#0B0E12), superficies elevadas apenas más claras,
bordes cabello fino rgba(255,255,255,.06), acento menta #34E0A1 como "verde
de billetera". Manrope con números tabulares; display 800 para el balance.
Estados: ok = menta, atención = ámbar #FFC24B, excedido/vencido = coral #FF6B6B.
STORY: "Cuánto tengo" un vistazo → "qué pide atención" (alertas) →
"qué movimientos hubo" — y una vía directa a registrar.
FIRST VIEWPORT: header tab fino; hero balance card con balance en display,
chips de ingreso/gasto del mes; debajo el banner de alertas (si hay) y la
lista "Movimientos" de alto contraste. Registrar sigue un tap más abajo.
FORM: neo-bank dark, pick del usuario, seed: user-pinned.
FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying its
provenance.

Scope: todo static/ (el sistema es compartido); el Panel recibe el detalle
principal; Metas y Agente heredan el sistema con ajustes mínimos.

Intacto: toda funcionalidad, copy de dominio, rutas, confirmaciones.
