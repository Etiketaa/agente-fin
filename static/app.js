/* Finanzas Personales — lógica del frontend */

"use strict";

const state = {
  currency: "ARS",
  provider: "mock",
  model: "mock",
  sensitiveAmount: 50000,
  budgetAlertPct: 0.8,
  period: "mes",
  categories: [],
  goals: [],
  accounts: [],
  lastAccount: null, // última billetera usada: se pre-selecciona al registrar
  budgetMonth: currentMonth(),
  billsVerTodos: false, // en Inicio solo se ven los 3 primeros pagos
  pending: null,
  chatMessages: [], // historial {role, content} enviado al backend
  incomeSources: [], // procedencias del mes, para los chips del formulario
};

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function moneyFmt(amount) {
  // La API devuelve montos en unidades de moneda (floats); acá solo se formatean.
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: state.currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

function pct(n) {
  return `${Math.round(n)}%`;
}

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function periodRange() {
  const today = new Date();
  const iso = (d) => d.toISOString().slice(0, 10);
  const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  if (state.period === "mes") return { desde: iso(firstOfMonth), hasta: iso(today) };
  if (state.period === "anio") {
    return { desde: iso(new Date(today.getFullYear(), 0, 1)), hasta: iso(today) };
  }
  return {};
}

const TOKEN_KEY = "finanzas_token";
const USER_KEY = "finanzas_user";

function authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...opts,
  });
  // opts.headers pisa los defaults si el llamador pasa los suyos
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) { /* sin cuerpo JSON */ }
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      // Sesión vencida o revocada: volver al login sin romper la página.
      logoutUI();
      throw new Error("Sesión vencida. Iniciá sesión de nuevo.");
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

let toastTimer = null;
function toast(message, kind = "") {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.disabled = true;
    button.textContent = "…";
  } else {
    button.disabled = false;
    button.textContent = button.dataset.label || label;
  }
}

// ---------------------------------------------------------------------------
// Config + categorías
// ---------------------------------------------------------------------------

async function loadConfig() {
  const cfg = await api("/api/config");
  state.currency = cfg.currency;
  state.provider = cfg.provider;
  state.model = cfg.model;
  state.sensitiveAmount = cfg.sensitive_amount;
  state.budgetAlertPct = cfg.budget_alert_pct;
  $("#alert-threshold").textContent = pct(state.budgetAlertPct * 100);
  if (state.provider === "mock") {
    $("#chat-fallback").classList.remove("hidden");
  }
}

async function loadCategories() {
  state.categories = await api("/api/categories");
  syncCategoryOptions();
  syncBudgetCategories();
  syncBillCategories();
}

// El selector de categoría depende del tipo elegido: una categoría de gasto no
// puede ser la de un ingreso. Antes se llenaba solo con gastos, así que elegir
// "Ingreso" y guardar siempre terminaba en un 400.
// Cambia tipo (gasto/ingreso) y redibuja los chips de categoría. El valor
// elegido vive en #tx-category (campo oculto): los chips son sólo la forma de
// elegirlo, para que sea un tap en vez de abrir un select y scrollear el
// picker nativo del teléfono.
function syncCategoryOptions() {
  const kind = $("#tx-type").value;
  const cont = $("#tx-category-chips");
  const propias = state.categories.filter((c) => c.kind === kind);
  const prev = $("#tx-category").value;

  cont.innerHTML = "";
  for (const c of propias) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = c.name;
    chip.setAttribute("role", "radio");
    chip.setAttribute("aria-checked", "false");
    chip.addEventListener("click", () => {
      $("#tx-category").value = c.name;
      cont.querySelectorAll(".chip").forEach((x) => {
        const on = x === chip;
        x.classList.toggle("active", on);
        x.setAttribute("aria-checked", on ? "true" : "false");
      });
    });
    cont.appendChild(chip);
  }
  // Antes el select arrancaba con la primera categoría; los chips arrancan con
  // la primera marcada, que es lo mismo pero a la vista.
  marcarChip($("#tx-category"), propias.some((c) => c.name === prev) ? prev : propias[0]?.name);

  // La procedencia solo tiene sentido en ingresos.
  const esIngreso = kind === "income";
  $("#tx-source-wrap").classList.toggle("hidden", !esIngreso);
  if (esIngreso) renderSourceChips();
  syncSubmitLabel();
}

function marcarChip(hidden, nombre) {
  const cont = $("#tx-category-chips");
  hidden.value = nombre || "";
  cont.querySelectorAll(".chip").forEach((x) => {
    const on = x.textContent === nombre;
    x.classList.toggle("active", on);
    x.setAttribute("aria-checked", on ? "true" : "false");
  });
}

function syncSubmitLabel() {
  const b = $("#tx-submit");
  const titulo = $("#sheet-movimiento-title");
  const esIngreso = $("#tx-type").value === "income";
  if (b) b.textContent = esIngreso ? "Registrar cobro" : "Registrar gasto";
  if (titulo) titulo.textContent = esIngreso ? "Registrar cobro" : "Registrar gasto";
}

// Chips de procedencia con lo que ya entró este mes. Vienen de
// GET /api/income, que el panel ya pide: no hay endpoint nuevo ni una request
// extra. El input de texto al lado sigue aceptando cualquier otra.
function renderSourceChips() {
  const cont = $("#tx-source-chips");
  if (!cont) return;
  const fuentes = (state.incomeSources || []).slice(0, 6);
  cont.innerHTML = "";
  if (!fuentes.length) {
    cont.classList.add("hidden");
    return;
  }
  cont.classList.remove("hidden");
  const input = $("#tx-source");
  for (const f of fuentes) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = f.source;
    chip.title = `${moneyFmt(f.total)} en ${f.count} cobro(s) este mes`;
    chip.addEventListener("click", () => {
      input.value = input.value === f.source ? "" : f.source;
      cont.querySelectorAll(".chip").forEach((x) => x.classList.toggle("active", x === chip && input.value));
    });
    if (input.value === f.source) chip.classList.add("active");
    cont.appendChild(chip);
  }
}

function syncBudgetCategories() {
  const select = $("#budget-category");
  const prev = select.value;
  select.innerHTML = "";
  for (const c of state.categories) {
    if (c.kind !== "expense") continue;
    const opt = document.createElement("option");
    opt.value = c.name;
    opt.textContent = c.name;
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === prev)) select.value = prev;
}

// ---------------------------------------------------------------------------
// Panel financiero
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Billeteras (patrimonio: cuánta plata hay y dónde)
// ---------------------------------------------------------------------------

const ACCOUNT_ICON = { banco: "🏦", digital: "📱", efectivo: "💵", otro: "👛" };

function cuentaIcon(kind) {
  return ACCOUNT_ICON[kind] || ACCOUNT_ICON.otro;
}

// La billetera de un movimiento, o null si no se puede mostrar (sin asignar o
// con una billetera que ya no existe).
function cuentaDe(t) {
  const acc = state.accounts.find((a) => a.name === t.cuenta);
  if (!acc || acc.es_default) return null;
  return { icon: cuentaIcon(acc.kind), name: acc.name };
}

async function renderAccounts() {
  const data = await api("/api/accounts");
  state.accounts = data.accounts;

  const total = $("#patrimonio-total");
  total.textContent = moneyFmt(data.total);
  total.classList.toggle("pos", data.total >= 0);
  total.classList.toggle("neg", data.total < 0);

  // Si el usuario todavía no cargó ninguna billetera real, el "patrimonio" es en
  // realidad sólo la diferencia entre ingresos y gastos registrados. Decirlo es
  // la diferencia entre un número útil y uno que miente (ver DESIGN.md).
  const reales = data.accounts.filter((a) => !a.es_default);
  const aviso = $("#patrimonio-aviso");
  aviso.textContent = reales.length
    ? ""
    : "Todavía no cargaste ninguna billetera: este total es sólo la diferencia entre tus ingresos y gastos registrados, no tu plata.";

  const box = $("#accounts-list");
  box.innerHTML = "";
  if (!data.accounts.length) {
    box.innerHTML = `<div class="no-data">Sin billeteras cargadas.</div>`;
    syncAccountOptions();
    return;
  }
  for (const a of data.accounts) {
    const row = document.createElement("div");
    row.className = "account-row";
    const sub = a.es_default
      ? "Movimientos sin billetera asignada"
      : a.movimientos
        ? `${a.movimientos} mov.${a.ultimo_movimiento ? " · último " + a.ultimo_movimiento : ""}`
        : "sin movimientos";
    row.innerHTML = `
      <span class="account-icon">${cuentaIcon(a.kind)}</span>
      <span class="account-main">
        <span class="account-name">${esc(a.name)}</span>
        <span class="muted small">${esc(sub)}</span>
      </span>
      <span class="account-amt num ${a.balance >= 0 ? "pos" : "neg"}">${moneyFmt(a.balance)}</span>
      <span class="account-acts">
        ${
          a.es_default
            ? ""
            : `<button class="btn ghost small-btn" data-edit-account="${a.id}" title="Ajustar saldo de ${esc(a.name)}">✎</button>`
        }
      </span>`;
    box.appendChild(row);
  }
  box.querySelectorAll("[data-edit-account]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const acc = state.accounts.find((a) => a.id === Number(btn.dataset.editAccount));
      openAccountForm(acc);
    });
  });
  syncAccountOptions();
}

function syncAccountOptions() {
  const sel = $("#tx-cuenta");
  if (!sel) return;
  const previo = state.lastAccount || sel.value;
  sel.innerHTML = "";
  // Las billeteras reales van primero y «General» al final: es el destino de los
  // movimientos sueltos, no la billetera que uno elige por defecto.
  const orden = [...state.accounts].sort((a, b) => Number(a.es_default) - Number(b.es_default));
  for (const a of orden) {
    const opt = document.createElement("option");
    opt.value = a.name;
    opt.textContent = cuentaIcon(a.kind) + " " + a.name + (a.es_default ? " (sin asignar)" : "");
    sel.appendChild(opt);
  }
  // Preferencia: la última billetera usada (casi siempre es la misma).
  const existe = [...sel.options].some((o) => o.value === previo);
  const primeraReal = orden.find((a) => !a.es_default);
  sel.value = existe ? previo : (primeraReal ? primeraReal.name : (orden[0] ? orden[0].name : ""));
}

// Alta de billetera (modo crear) y conciliación de saldo (modo ajustar).
function openAccountForm(account) {
  const form = $("#account-form");
  form.dataset.id = account ? String(account.id) : "";
  $("#sheet-account-title").textContent = account
    ? `Ajustar saldo — ${account.name}`
    : "Nueva billetera";
  $("#account-name").value = account ? account.name : "";
  $("#account-kind").value = account ? account.kind : "digital";
  $("#account-notes").value = account ? account.notes || "" : "";
  $("#account-saldo").value = account ? account.balance : "";
  $("#account-submit").textContent = account ? "Ajustar saldo" : "Agregar billetera";
  $("#account-hint").textContent = account
    ? "Poné el saldo que figura hoy en la app del banco: el total se corrige solo, sin tocar los movimientos."
    : "Es el saldo que figura en la app del banco ahora. Queda como base y de ahí en adelante se calcula solo.";
  // Borrar vive acá adentro y no en la fila: primero abrís la billetera.
  $("#account-danger").classList.toggle("hidden", !account);
  if (account) {
    $("#account-delete").textContent = account.movimientos
      ? `Eliminar billetera (sus ${account.movimientos} movimiento(s) pasan a «General»)`
      : "Eliminar billetera";
  }
  openSheet("#sheet-account");
  setTimeout(() => $(account ? "#account-saldo" : "#account-name").focus(), 120);
}

async function onSubmitAccount(e) {
  e.preventDefault();
  const form = e.target;
  const id = form.dataset.id;
  const payload = {
    name: $("#account-name").value.trim(),
    kind: $("#account-kind").value,
    saldo: parseFloat($("#account-saldo").value || "0") || 0,
    notes: $("#account-notes").value.trim(),
  };
  try {
    if (id) {
      await api(`/api/accounts/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast("Saldo actualizado", "success");
    } else {
      const nueva = await api("/api/accounts", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      // La billetera recién creada pasa a ser la pre-seleccionada.
      state.lastAccount = nueva.name;
      toast("Billetera agregada", "success");
    }
    form.reset();
    closeSheets();
    await refreshPanel();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteAccount(id) {
  const acc = state.accounts.find((a) => a.id === id);
  const extra =
    acc && acc.movimientos
      ? `\nSus ${acc.movimientos} movimiento(s) pasarán a «General».`
      : "";
  if (!confirm(`¿Eliminar la billetera «${acc ? acc.name : id}»?${extra}`)) return;
  try {
    await api(`/api/accounts/${id}?reasignar=1`, { method: "DELETE" });
    if (state.lastAccount === (acc ? acc.name : null)) state.lastAccount = null;
    toast("Billetera eliminada", "success");
    closeSheets();
    await refreshPanel();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function renderSummary() {
  const range = periodRange();
  const qs = new URLSearchParams(range).toString();
  const s = await api(`/api/summary?${qs}`);
  $("#sum-balance").textContent = moneyFmt(s.balance);
  $("#sum-balance").parentElement.classList.toggle("pos", s.balance >= 0);
  $("#sum-balance").parentElement.classList.toggle("neg", s.balance < 0);
  $("#sum-income").textContent = moneyFmt(s.total_income);
  $("#sum-expense").textContent = moneyFmt(s.total_expense);
  $("#sum-income-hero").textContent = moneyFmt(s.total_income);
  $("#sum-expense-hero").textContent = moneyFmt(s.total_expense);
  $("#sum-count").textContent = s.count;
  $("#period-info").textContent = `Período: ${s.period}`;
  // El selector de período vive en Movimientos, así que el hero dice cuál está
  // usando: si no, este número cambia en silencio desde otra pantalla.
  $("#hero-period").textContent = s.period === "todo el historial" ? "(todo)" : `· ${s.period}`;
  renderDisponible(s);
  renderPagosResumen(s);

  // Barras: gastos por categoría
  const bars = $("#category-bars");
  const expenses = s.by_category.filter((c) => c.kind === "expense");
  if (!expenses.length) {
    bars.innerHTML = `<div class="no-data">Sin gastos en este período.</div>`;
    return;
  }
  const max = Math.max(...expenses.map((c) => c.total));
  bars.innerHTML = "";
  for (const c of expenses) {
    const p = Math.round((c.total / max) * 100);
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <div class="bar-top"><span>${esc(c.category)}</span><span class="num">${moneyFmt(c.total)}</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${p}%"></div></div>`;
    bars.appendChild(row);
  }
}

// "Disponible real" = patrimonio − lo que ya sabés que tenés que pagar.
// Sin esto, el resultado del período de arriba se lee como "tengo esta plata",
// que es justo la confusión que hace inútil el número.
function renderDisponible(s) {
  const disp = $("#sum-disponible");
  const comp = $("#hero-comprometido");
  const venc = $("#hero-vencido");
  disp.textContent = moneyFmt(s.disponible);
  disp.classList.toggle("neg", s.disponible < 0);

  if (s.comprometido_cents > 0) {
    // "2 vencimientos" y no "pagos": uno todavía no venció, no es un pago.
    const n = s.comprometido_count;
    const cant = `${n} vencimiento${n === 1 ? "" : "s"}`;
    // El desglose del mes sólo suma cuando difiere del total: repetir
    // "450.000 ... (450.000 este mes)" es ruido.
    const detalle = s.comprometido_mes_cents > 0 && s.comprometido_mes_cents !== s.comprometido_cents
      ? `, ${moneyFmt(s.comprometido_mes)} este mes`
      : "";
    comp.textContent = `después de ${moneyFmt(s.comprometido)} en ${cant} pendiente${n === 1 ? "" : "s"}${detalle}`;
  } else {
    comp.textContent = "no tenés vencimientos pendientes";
  }

  // Lo vencido se destaca sólo si existe: es plata que ya se fue de la cuenta
  // pero todavía no salió de tu patrimonio.
  if (s.vencido_cents > 0) {
    const n = s.vencido_count;
    venc.textContent = `${moneyFmt(s.vencido)} ya ${n === 1 ? "venció" : "vencieron"} sin pagar`;
    venc.classList.remove("hidden");
  } else {
    venc.classList.add("hidden");
  }
}

// Iconos por categoría (más escaneables que texto en un feed de app).
const CAT_ICON = {
  Comida: "🛒", Transporte: "🚌", Vivienda: "🏠", Servicios: "💡",
  Salud: "🏥", "Educación": "📚", Ocio: "🎮", Motos: "🏍️",
  Compras: "🛍️", Otros: "📦", Sueldo: "💼", Freelance: "💻",
  "Otros ingresos": "💸",
};

function dayLabel(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
  const diff = Math.round((hoy - date) / 86400000);
  if (diff === 0) return "Hoy";
  if (diff === 1) return "Ayer";
  return date.toLocaleDateString("es-AR", { weekday: "short", day: "numeric", month: "short" });
}

async function renderTransactions() {
  const range = periodRange();
  const qs = new URLSearchParams({ ...range, limite: "40" }).toString();
  const rows = await api(`/api/transactions?${qs}`);
  const feed = $("#tx-feed");
  if (!rows.length) {
    feed.innerHTML = `<div class="no-data">Sin movimientos en este período.</div>`;
    return;
  }
  // Agrupar por día (la API ya viene ordenada desc).
  const groups = new Map();
  for (const t of rows) {
    if (!groups.has(t.date)) groups.set(t.date, []);
    groups.get(t.date).push(t);
  }
  feed.innerHTML = "";
  for (const [dia, items] of groups) {
    const g = document.createElement("div");
    g.className = "feed-day";
    const total = items.reduce((acc, t) => acc + (t.type === "income" ? t.amount : -t.amount), 0);
    const totalCls = total >= 0 ? "pos" : "neg";
    const totalSign = total >= 0 ? "+" : "−";
    g.innerHTML = `
      <div class="feed-day-head">
        <span>${esc(dayLabel(dia))}</span>
        <span class="num ${totalCls}">${totalSign}${moneyFmt(Math.abs(total))}</span>
      </div>
      <div class="feed-items"></div>`;
    const list = g.querySelector(".feed-items");
    for (const t of items) {
      const isIncome = t.type === "income";
      const icon = CAT_ICON[t.category] || (isIncome ? "💸" : "📦");
      const cc = cuentaDe(t);
      const chips = [
        t.source ? `<span class="tag source">💵 ${esc(t.source)}</span>` : "",
        t.goal ? `<span class="tag goal">🎯 ${esc(t.goal)}</span>` : "",
        // La billetera sólo cuando NO es «General»: mostrarla siempre sería ruido.
        cc ? `<span class="tag cuenta">${cc.icon} ${esc(cc.name)}</span>` : "",
      ].filter(Boolean).join(" ");
      const item = document.createElement("div");
      item.className = "feed-item";
      item.innerHTML = `
        <span class="feed-icon">${icon}</span>
        <span class="feed-main">
          <span class="feed-desc">${esc(t.description || t.category)}</span>
          <span class="feed-sub muted small">${esc(t.category)}${chips ? " · " : ""}${chips}</span>
        </span>
        <span class="feed-amt num ${isIncome ? "pos" : "neg"}">${isIncome ? "+" : "−"}${moneyFmt(t.amount)}</span>
        <button class="btn ghost small-btn feed-del" data-del="${t.id}" title="Eliminar">✕</button>`;
      list.appendChild(item);
    }
    feed.appendChild(g);
  }
  feed.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar el movimiento #${btn.dataset.del}?`)) return;
      try {
        await api(`/api/transactions/${btn.dataset.del}`, { method: "DELETE" });
        toast("Movimiento eliminado", "success");
        await refreshPanel();
      } catch (e) {
        toast(e.message, "error");
      }
    });
  });
}

async function loadAlerts() {
  // Centro de alertas unificado: vencimientos, presupuestos, objetivos y
  // anomalías salen de la misma función del backend que usa el agente.
  const box = $("#budget-alerts");
  const alerts = await api("/api/alerts");
  if (!alerts.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  const items = alerts.map((a) => `<li>${esc(a.message)}</li>`).join("");
  box.innerHTML = `
    <div class="alert-box">
      <div class="alert-title">⚠️ Requiere tu atención (${alerts.length})</div>
      <ul>${items}</ul>
    </div>`;
  box.classList.remove("hidden");
}

// Ingresos del mes actual: total, por procedencia y por día.
async function renderIncome() {
  const data = await api("/api/income");
  // El formulario de ingreso arma los chips de procedencia con esto, así que no
  // hace falta volver a pedirlo cuando se abre la sheet.
  state.incomeSources = data.by_source;
  $("#income-head").innerHTML = data.count
    ? `<strong>${moneyFmt(data.total)}</strong> <span class="muted">en ${data.count} cobro(s) durante ${esc(data.month)}</span>`
    : "";
  const src = $("#income-sources");
  const days = $("#income-days");
  if (!data.count) {
    src.innerHTML = "";
    days.innerHTML = `<div class="no-data">Sin ingresos en este mes todavía.</div>`;
    return;
  }
  const maxSrc = Math.max(...data.by_source.map((s) => s.total));
  src.innerHTML = data.by_source.map((s) => {
    const p = Math.round((s.total / maxSrc) * 100);
    return `
      <div class="bar-row">
        <div class="bar-top"><span>${esc(s.source)} <span class="muted">(${s.count})</span></span><span class="num pos">${moneyFmt(s.total)}</span></div>
        <div class="bar-track"><div class="bar-fill income-fill" style="width:${p}%"></div></div>
      </div>`;
  }).join("");
  days.innerHTML = data.days.map((d) => {
    const items = d.items.map((t) =>
      `<li>💵 <strong>${esc(t.source || "(sin procedencia)")}</strong> · ${t.description ? esc(t.description) + " · " : ""}<span class="num pos">${moneyFmt(t.amount)}</span></li>`
    ).join("");
    return `
      <div class="income-day">
        <div class="income-day-head"><span>${esc(d.date)}</span><span class="num pos">${moneyFmt(d.total)}</span></div>
        <ul>${items}</ul>
      </div>`;
  }).join("");
}

async function refreshPanel() {
  // allSettled y no all: si un endpoint falla, el resto del panel tiene que
  // seguir mostrando algo. Con Promise.all, un solo fallo dejaba el panel a
  // medio cargar sin explicar por qué.
  const tareas = [
    ["resumen", renderSummary],
    ["billeteras", renderAccounts],
    ["movimientos", renderTransactions],
    ["objetivos", loadGoals],
    ["presupuestos", loadBudgets],
    ["vencimientos", loadBills],
    ["ingresos", renderIncome],
    ["alertas", loadAlerts],
  ];
  const fallos = await Promise.allSettled(tareas.map(([, fn]) => fn()));
  const errores = fallos
    .map((r, i) => (r.status === "rejected" ? `${tareas[i][0]}: ${r.reason?.message || r.reason}` : null))
    .filter(Boolean);
  if (errores.length) {
    console.error("Fallas al recargar el panel:", errores);
    toast(`No se pudo actualizar: ${errores.join(" · ")}`, "error");
  }
}

// Los tres números de la card de pagos. La lista de vencimientos contesta
// "cuáles", pero no "cuánta plata hay que sacar": con ocho filas hay que
// sumarlas a mano. El hero ya dice el disponible real, que es otra pregunta
// (patrimonio menos comprometido); acá va la del-pocket.
function renderPagosResumen(s) {
  const box = $("#pagos-resumen");
  if (!box) return;
  // Sin vencimientos no hay nada que resumir: la lista dice que no tenés.
  if (!s.comprometido_count) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  const n = s.comprometido_count;
  // Lo que queda una vez pagada la parte vencida. En centavos, que es como
  // viaja el dinero por la API: la resta se hace acá y se formatea recién.
  const quedaCents = Math.max(0, s.comprometido_cents - s.vencido_cents);
  const queda = quedaCents / 100;

  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="pagos-dato">
      <span class="card-label">Total a pagar</span>
      <span class="pagos-valor num">${moneyFmt(s.comprometido)}</span>
      <span class="muted small">en ${n} vencimiento${n === 1 ? "" : "s"}</span>
    </div>
    ${
      s.vencido_cents > 0
        ? `<div class="pagos-dato pagos-dato-urgent">
             <span class="card-label">Vencido</span>
             <span class="pagos-valor num">${moneyFmt(s.vencido)}</span>
             <span class="muted small">${s.vencido_count === 1 ? "1 pago que se pasó" : `${s.vencido_count} pagos que se pasaron`}</span>
           </div>
           <div class="pagos-dato">
             <span class="card-label">Si pagás lo vencido</span>
             <span class="pagos-valor num">${moneyFmt(queda)}</span>
             <span class="muted small">te quedan por delante</span>
           </div>`
        : `<div class="pagos-dato">
             <span class="card-label">Vencido</span>
             <span class="pagos-valor num">—</span>
             <span class="muted small">nada vencido</span>
           </div>`
    }`;
}

// ---------------------------------------------------------------------------
// Objetivos de ahorro
// ---------------------------------------------------------------------------

async function loadGoals() {
  state.goals = await api("/api/goals");
  // El selector del formulario de movimiento
  const select = $("#tx-goal");
  const prev = select.value;
  select.innerHTML = `<option value="">— ninguno —</option>`;
  for (const g of state.goals) {
    const opt = document.createElement("option");
    opt.value = g.name;
    // Icono según el tipo, para no confundir plata tuya con plata recaudada.
    opt.textContent = (g.kind === "recaudacion" ? "🧺 " : "🎯 ") + g.name;
    if (g.kind === "recaudacion") opt.title = "Al asignar: ingresos suman, gastos restan";
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === prev)) select.value = prev;
  renderGoals();
}

function renderGoals() {
  const box = $("#goals-list");
  if (!state.goals.length) {
    box.innerHTML = `<div class="no-data">Todavía no tenés objetivos. Creá el primero arriba.</div>`;
    return;
  }
  box.innerHTML = "";
  for (const g of state.goals) {
    const el = document.createElement("div");
    el.className = `goal-card ${g.status}`;
    const parts = [];
    if (g.status === "alcanzado") parts.push("🎉 ¡Alcanzado!");
    else if (g.status === "vencido") parts.push("⏰ Venció sin completarse");
    if (g.required_per_month) {
      parts.push(`faltan ${moneyFmt(g.required_per_month)} por mes para llegar a la fecha`);
    }
    const extra = parts.length
      ? `<div class="goal-extra">${parts.map(esc).join(" · ")}</div>`
      : "";
    const fecha = g.target_date ? esc(g.target_date) : "sin fecha límite";
    const badge = g.kind === "recaudacion"
      ? ` <span class="tag goal-kind">🧺 recaudación</span>`
      : ` <span class="tag goal-kind">🎯 ahorro</span>`;
    // En una meta de recaudación el número grande es la resta (recaudado menos
    // gastado), que no se puede explicar solo. El desglose dice de dónde sale.
    // En una meta de ahorro no: lo que aporta es plata y ya se ve.
    const desglose = g.kind === "recaudacion" && g.income_cents
      ? `<div class="goal-desglose">
           <span class="goal-desglose-dato"><span class="muted small">recaudado</span> <span class="num pos">${moneyFmt(g.income)}</span></span>
           <span class="goal-desglose-dato"><span class="muted small">gastado</span> <span class="num neg">${moneyFmt(g.expense)}</span></span>
           <span class="goal-desglose-dato"><span class="muted small">disponible</span> <span class="num"><strong>${moneyFmt(g.saved)}</strong></span></span>
         </div>`
      : "";
    el.innerHTML = `
      <div class="goal-head">
        <div>
          <div class="goal-name">${esc(g.name)}${badge}</div>
          <div class="muted small">${fecha}${g.notes ? ` · ${esc(g.notes)}` : ""}</div>
        </div>
        <button class="btn ghost small-btn" data-del-goal="${g.id}" title="Eliminar objetivo">✕</button>
      </div>
      <div class="bar-track goal-track">
        <div class="bar-fill" style="width:${Math.min(g.percent, 100)}%"></div>
      </div>
      <div class="bar-top">
        <span class="num"><strong>${moneyFmt(g.saved)}</strong> de ${moneyFmt(g.target_amount)}</span>
        <span class="muted">${pct(g.percent)}</span>
      </div>
      ${desglose}
      ${extra}`;
    box.appendChild(el);
  }
  box.querySelectorAll("[data-del-goal]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar el objetivo #${btn.dataset.delGoal}?`)) return;
      try {
        await api(`/api/goals/${btn.dataset.delGoal}`, { method: "DELETE" });
        toast("Objetivo eliminado", "success");
        await refreshPanel();
      } catch (e) {
        toast(e.message, "error");
      }
    });
  });
}

async function onSubmitGoal(e) {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  const payload = {
    name: $("#goal-name").value.trim(),
    target_amount: parseFloat($("#goal-amount").value),
    target_date: $("#goal-date").value || null,
    kind: $("#goal-kind").value,
  };
  setBusy(btn, true);
  try {
    await api("/api/goals", { method: "POST", body: JSON.stringify(payload) });
    toast("Objetivo creado", "success");
    e.target.reset();
    await refreshPanel();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

// ---------------------------------------------------------------------------
// Presupuestos
// ---------------------------------------------------------------------------

async function loadBudgets() {
  const rows = await api(`/api/budgets?mes=${state.budgetMonth}`);
  renderBudgets(rows);
  // El banner del panel lo alimenta loadAlerts (/api/alerts), que ya incluye
  // los presupuestos del mes en curso junto al resto de las alertas.
}

// Una fila de presupuesto, dos presentaciones: la de Inicio (consulta) y la de
// Metas (consulta + eliminar). El texto, el ícono y la barra salen de acá una
// sola vez, así las dos pantallas no pueden mostrar números distintos.
function budgetRowHtml(b, conBorrar) {
  const partes = [];
  if (b.remaining_cents < 0) partes.push(`te pasaste por ${moneyFmt(Math.abs(b.remaining))}`);
  else partes.push(`quedan ${moneyFmt(b.remaining)}`);
  if (b.days_left) partes.push(`faltan ${b.days_left} días`);
  if (b.projected_cents > b.limit_cents && b.status !== "excedido") {
    partes.push(`a este ritmo terminás el mes en ${moneyFmt(b.projected)}`);
  }
  const icon = b.status === "excedido" ? "🔴" : b.status === "atencion" ? "🟡" : "🟢";
  const borrar = conBorrar
    ? `<button class="btn ghost small-btn" data-del-budget="${b.id}" title="Eliminar presupuesto">✕</button>`
    : "";
  return `
    <div class="goal-head">
      <div>
        <div class="goal-name">${icon} ${esc(b.category)}</div>
        <div class="muted small">${partes.map(esc).join(" · ")}</div>
      </div>
      ${borrar}
    </div>
    <div class="bar-track goal-track">
      <div class="bar-fill" style="width:${Math.min(b.percent, 100)}%"></div>
    </div>
    <div class="bar-top">
      <span class="num"><strong>${moneyFmt(b.spent)}</strong> de ${moneyFmt(b.limit)}</span>
      <span class="muted">${pct(b.percent)}</span>
    </div>`;
}

function renderBudgets(rows) {
  const lista = $("#budgets-list");
  const strip = $("#budgets-strip");
  if (!rows.length) {
    const vacio = `<div class="no-data">No hay presupuestos cargados para este mes.</div>`;
    lista.innerHTML = vacio;
    strip.innerHTML = vacio;
    return;
  }
  lista.innerHTML = rows
    .map((b) => `<div class="budget-card ${b.status}">${budgetRowHtml(b, true)}</div>`)
    .join("");
  strip.innerHTML = rows
    .map((b) => `<div class="budget-card ${b.status}">${budgetRowHtml(b, false)}</div>`)
    .join("");

  lista.querySelectorAll("[data-del-budget]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar el presupuesto #${btn.dataset.delBudget}?`)) return;
      try {
        await api(`/api/budgets/${btn.dataset.delBudget}`, { method: "DELETE" });
        toast("Presupuesto eliminado", "success");
        await refreshPanel();
      } catch (e) {
        toast(e.message, "error");
      }
    });
  });
}

async function onSubmitBudget(e) {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  const payload = {
    category: $("#budget-category").value,
    amount: parseFloat($("#budget-amount").value),
  };
  setBusy(btn, true);
  try {
    await api("/api/budgets", { method: "POST", body: JSON.stringify(payload) });
    toast("Presupuesto guardado", "success");
    $("#budget-amount").value = "";
    await refreshPanel();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

// ---------------------------------------------------------------------------
// Vencimientos
// ---------------------------------------------------------------------------

function syncBillCategories() {
  const select = $("#bill-category");
  const prev = select.value;
  select.innerHTML = "";
  for (const c of state.categories) {
    if (c.kind !== "expense") continue;
    const opt = document.createElement("option");
    opt.value = c.name;
    opt.textContent = c.name;
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === prev)) select.value = prev;
}

function billCuando(b) {
  if (b.state === "vencido") return `venció hace ${-b.days_until} día(s)`;
  if (b.days_until === 0) return "vence hoy";
  if (b.days_until === 1) return "vence mañana";
  return `vence en ${b.days_until} días (${esc(b.due_date)})`;
}

async function loadBills() {
  const rows = await api("/api/bills");
  const box = $("#bills-list");
  syncBillCategories();
  if (!rows.length) {
    box.innerHTML = `<div class="no-data">Sin vencimientos pendientes. Agregá el primero arriba.</div>`;
    return;
  }

  // En Inicio se muestran solo los primeros: la card tiene que responder
  // "¿qué pago ahora?" de un vistazo, no ser la lista completa. Con 8
  // vencimientos, el scroll hasta "Gastos por categoría" era de tres pantallas.
  // "Ver todos" los muestra igual, acá mismo: nada queda escondido sin salida.
  const LIMITE = 3;
  const verTodos = state.billsVerTodos;
  const visibles = verTodos ? rows : rows.slice(0, LIMITE);
  const quedan = rows.length - visibles.length;

  box.innerHTML = "";
  for (const b of visibles) {
    const el = document.createElement("div");
    el.className = `bill-card ${b.state}`;
    const icon = b.state === "vencido" ? "🔴" : b.state === "proximo" ? "🟡" : "⚪";
    const rec = b.recurrence === "monthly" ? " · mensual" : "";
    el.innerHTML = `
      <div class="goal-head">
        <div>
          <div class="goal-name">${icon} ${esc(b.description)}</div>
          <div class="muted small">${billCuando(b)} · ${esc(b.category)}${esc(rec)}</div>
        </div>
        <div class="bill-actions">
          <span class="num"><strong>${moneyFmt(b.amount)}</strong></span>
          <button class="btn primary small-btn" data-pay-bill="${b.id}" title="Marcar como pagado (genera el gasto)">Pagar</button>
          <button class="btn ghost small-btn" data-del-bill="${b.id}" title="Eliminar vencimiento">✕</button>
        </div>
      </div>`;
    box.appendChild(el);
  }

  if (quedan > 0 || verTodos) {
    const mas = document.createElement("button");
    mas.type = "button";
    mas.className = "btn ghost bills-mas";
    mas.id = "bills-mas";
    mas.textContent = verTodos
      ? "Ver menos"
      : `Ver los ${rows.length - LIMITE} pago${rows.length - LIMITE === 1 ? "" : "s"} más`;
    mas.addEventListener("click", async () => {
      state.billsVerTodos = !state.billsVerTodos;
      await loadBills();
    });
    box.appendChild(mas);
  }

  box.querySelectorAll("[data-pay-bill]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Marcar como pagado y generar el gasto?`)) return;
      try {
        const res = await api(`/api/bills/${btn.dataset.payBill}/pay`, { method: "POST" });
        toast(
          res.next_bill
            ? `Pagado. Se creó el siguiente para el ${res.next_bill.due_date}`
            : "Pagado y gasto registrado",
          "success"
        );
        await refreshPanel();
      } catch (e) {
        toast(e.message, "error");
      }
    });
  });
  box.querySelectorAll("[data-del-bill]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar el vencimiento #${btn.dataset.delBill}?`)) return;
      try {
        await api(`/api/bills/${btn.dataset.delBill}`, { method: "DELETE" });
        toast("Vencimiento eliminado", "success");
        await refreshPanel();
      } catch (e) {
        toast(e.message, "error");
      }
    });
  });
}

async function onSubmitBill(e) {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  const payload = {
    description: $("#bill-desc").value.trim(),
    amount: parseFloat($("#bill-amount").value),
    due_date: $("#bill-date").value,
    category: $("#bill-category").value,
    recurrence: $("#bill-recurrence").value,
  };
  setBusy(btn, true);
  try {
    await api("/api/bills", { method: "POST", body: JSON.stringify(payload) });
    toast("Vencimiento agregado", "success");
    e.target.reset();
    closeSheets();
    await refreshPanel();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

// ---------------------------------------------------------------------------
// Alta de movimiento
// ---------------------------------------------------------------------------

async function onSubmitTx(e) {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  const amount = parseFloat($("#tx-amount").value);
  const tipo = $("#tx-type").value;
  const esIngreso = tipo === "income";
  const categoria = $("#tx-category").value;
  // El campo oculto no valida required (el navegador no valida campos hidden),
  // así que la categoría se chequea acá. Sin esto, un POST sin categoría
  // rebotaba con un 400 del backend en vez de avisarle acá.
  if (!categoria) {
    toast("Elegí una categoría", "error");
    $("#tx-category-chips").scrollIntoView({ block: "nearest" });
    return;
  }
  const payload = {
    type: esIngreso ? "income" : "expense",
    amount,
    category: categoria,
    goal: $("#tx-goal").value || null,
    description: $("#tx-description").value.trim(),
    date: $("#tx-date").value || null,
    // La procedencia solo se manda en ingresos; en gastos se ignora.
    source: esIngreso ? ($("#tx-source").value.trim() || null) : null,
    // Billetera: es lo que mantiene vivo el saldo de cada una.
    cuenta: $("#tx-cuenta").value || null,
  };
  setBusy(btn, true);
  try {
    await api("/api/transactions", { method: "POST", body: JSON.stringify(payload) });
    toast("Movimiento registrado", "success");
    // Recordamos la billetera usada: casi siempre es la misma y evita elegirla.
    state.lastAccount = payload.cuenta;
    e.target.reset();
    // form.reset() NO vacía los campos ocultos: al asignar input.value, este
    // Chrome escribe también el atributo value, y reset() restaura el atributo.
    // Los de tipo text/number sí se vacían. Los ocultos hay que limpiarlos a
    // mano, y al tipo hay que devolverle el que estaba elegido (registrar tres
    // cobros seguidos es lo normal).
    $("#tx-type").value = tipo;
    $("#tx-category").value = "";
    $("#tx-date").value = new Date().toISOString().slice(0, 10);
    closeSheets();
    syncCategoryOptions();
    await refreshPanel();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

// ---------------------------------------------------------------------------
// Agente (chat)
// ---------------------------------------------------------------------------

function appendMsg(role, html, kind = "") {
  const log = $("#chat-log");
  const div = document.createElement("div");
  div.className = `msg ${role} ${kind}`;
  div.innerHTML = html;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function typingBubble() {
  const log = $("#chat-log");
  const div = document.createElement("div");
  div.className = "msg assistant typing";
  div.textContent = "…";
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function renderPending(action) {
  const area = $("#pending-area");
  area.innerHTML = "";
  const card = document.createElement("div");
  card.className = "pending-card";
  card.innerHTML = `
    <div class="pending-title">⚠️ Se requiere tu confirmación</div>
    <div class="pending-summary">${esc(action.summary)}</div>
    <div class="pending-actions">
      <button class="btn confirm" id="pending-yes">Confirmar</button>
      <button class="btn ghost" id="pending-no">Cancelar</button>
    </div>`;
  area.appendChild(card);

  $("#pending-yes").addEventListener("click", async () => {
    setBusy($("#pending-yes"), true);
    try {
      const res = await api("/api/agent/confirm", {
        method: "POST",
        body: JSON.stringify({
          messages: state.chatMessages,
          pending_action: state.pending,
        }),
      });
      state.pending = null;
      renderPending(null);
      handleAgentResponse(res);
      await refreshPanel();
    } catch (err) {
      toast(err.message, "error");
      renderPending(null);
      state.pending = null;
    }
  });

  $("#pending-no").addEventListener("click", () => {
    state.pending = null;
    renderPending(null);
    appendMsg("assistant", "Listo, acción cancelada.");
    $("#chat-input").focus();
  });
}

function handleAgentResponse(res) {
  if (res.pending_action) {
    state.pending = res.pending_action;
    renderPending(res.pending_action);
  } else {
    appendMsg("assistant", esc(res.reply || "…"));
    state.chatMessages.push({ role: "assistant", content: res.reply || "" });
  }
  $("#chat-input").focus();
}

async function sendMessage(text) {
  state.chatMessages.push({ role: "user", content: text });
  appendMsg("user", esc(text));
  const bubble = typingBubble();
  try {
    const res = await api("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({ messages: state.chatMessages }),
    });
    if (res.reply) {
      bubble.innerHTML = esc(res.reply);
      state.chatMessages.push({ role: "assistant", content: res.reply });
    } else {
      bubble.remove();
    }
    handleAgentResponse(res);
    // El agente pudo registrar o eliminar movimientos: el panel va detrás.
    refreshPanel();
  } catch (err) {
    bubble.remove();
    appendMsg("error", `Error: ${esc(err.message)}`, "error");
  }
}

function onSubmitChat(e) {
  e.preventDefault();
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text || state.pending) return;
  input.value = "";
  sendMessage(text);
}

// ---------------------------------------------------------------------------
// Autenticación
// ---------------------------------------------------------------------------

let authMode = "login";

function showAuth() {
  $("#auth-screen").classList.remove("hidden");
  $("#main-container").classList.add("hidden");
  $("#user-box").classList.add("hidden");
  $("#fab-wrap").classList.add("hidden");
}

function enterApp(username) {
  $("#auth-screen").classList.add("hidden");
  $("#main-container").classList.remove("hidden");
  $("#user-box").classList.remove("hidden");
  $("#fab-wrap").classList.remove("hidden");
  $("#user-name").textContent = username || localStorage.getItem(USER_KEY) || "";
}

function logoutUI() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  state.pending = null;
  state.chatMessages = [];
  showAuth();
}

async function onSubmitAuth(e) {
  e.preventDefault();
  const btn = $("#auth-submit");
  const err = $("#auth-error");
  err.classList.add("hidden");
  const payload = {
    username: $("#auth-username").value.trim(),
    password: $("#auth-password").value,
  };
  setBusy(btn, true);
  try {
    const res = await api(`/api/auth/${authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    localStorage.setItem(TOKEN_KEY, res.token);
    localStorage.setItem(USER_KEY, res.username);
    e.target.reset();
    enterApp(res.username);
    await loadConfig();
    await loadCategories();
    await refreshPanel();
  } catch (e2) {
    err.textContent = e2.message;
    err.classList.remove("hidden");
  } finally {
    setBusy(btn, false);
  }
}

async function onLogout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch (_) { /* igual salimos */ }
  logoutUI();
  toast("Sesión cerrada", "success");
}

function initAuthTabs() {
  $$("[data-auth]").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("[data-auth]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      authMode = btn.dataset.auth;
      $("#auth-submit").textContent = authMode === "login" ? "Entrar" : "Crear cuenta";
      $("#auth-error").classList.add("hidden");
    });
  });
}

// ---------------------------------------------------------------------------
// FAB: el gesto frecuente flota siempre abajo a la derecha, en todas las tabs
// ---------------------------------------------------------------------------

// Elige gasto o ingreso. El valor real vive siempre en #tx-type; los botones
// sólo lo escriben, así que el segmented control no puede quedar desfasado del
// estado. Lo usan tanto los dos botones como jumpToForm().
function setTxType(kind) {
  $("#tx-type").value = kind;
  $$("#tx-type-seg .seg-btn").forEach((b) => {
    const on = b.dataset.txType === kind;
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", on ? "true" : "false");
  });
  syncCategoryOptions();
}

function jumpToForm(type) {
  // FAB cobro/gasto: abre la bottom sheet del formulario directo.
  openSheet("#sheet-movimiento");
  setTxType(type);
  setTimeout(() => $("#tx-amount").focus(), 120);
}

function jumpToBills() {
  openSheet("#sheet-bill");
  setTimeout(() => $("#bill-desc").focus(), 120);
}

function jumpToChat() {
  showView("agent");
  const input = $("#chat-input");
  input.value = "¿cómo vengo este mes?";
  input.focus();
}

// Bottom sheets: un solo backdrop para los dos formularios de escritura.
function openSheet(sel) {
  closeSheets();
  $("#sheet-backdrop").classList.remove("hidden");
  $(sel).classList.remove("hidden");
  $(sel).classList.add("anim-in");
}

function closeSheets() {
  $("#sheet-backdrop").classList.add("hidden");
  $$(".sheet").forEach((s) => {
    s.classList.add("hidden");
    s.classList.remove("anim-in");
  });
}

function initSheets() {
  $("#sheet-backdrop").addEventListener("click", closeSheets);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheets(); });
  $$("[data-close-sheet]").forEach((b) => b.addEventListener("click", closeSheets));
  $("#btn-nuevo-bill").addEventListener("click", () => jumpToBills());
  $("#btn-nueva-cuenta").addEventListener("click", () => openAccountForm(null));
  $("#account-form").addEventListener("submit", onSubmitAccount);
  $("#account-delete").addEventListener("click", () => {
    const id = $("#account-form").dataset.id;
    if (id) deleteAccount(Number(id));
  });

  // Gasto / Ingreso
  $$("#tx-type-seg .seg-btn").forEach((b) =>
    b.addEventListener("click", () => setTxType(b.dataset.txType))
  );
  // "Más opciones": billetera, objetivo, fecha y descripción. Todo lo que se
  // cambia una vez y después no se toca.
  $("#tx-more-toggle").addEventListener("click", (e) => {
    const abierto = $("#tx-more").classList.toggle("hidden") === false;
    e.currentTarget.setAttribute("aria-expanded", abierto ? "true" : "false");
    e.currentTarget.textContent = abierto ? "Menos opciones" : "Más opciones";
  });
}

function initFab() {
  const wrap = $("#fab-wrap");
  const fab = $("#fab");
  const sheet = $("#fab-sheet");
  const close = () => {
    sheet.classList.add("hidden");
    fab.classList.remove("open");
    fab.setAttribute("aria-expanded", "false");
  };
  fab.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = !sheet.classList.contains("hidden");
    if (open) return close();
    sheet.classList.remove("hidden");
    fab.classList.add("open");
    fab.setAttribute("aria-expanded", "true");
  });
  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) close();
  });
  sheet.addEventListener("click", (e) => {
    const btn = e.target.closest(".fab-row");
    if (!btn) return;
    close();
    const acc = btn.dataset.action;
    if (acc === "cobro") jumpToForm("income");
    else if (acc === "gasto") jumpToForm("expense");
    else if (acc === "pagar") jumpToBills();
    else if (acc === "consulta") jumpToChat();
  });
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

// Muestra una vista y deja el destino marcado en las dos navs (la del header y
// la barra inferior). Que el estado activo salga de `data-view` y no del botón
// que se apretó es lo que impide que las dos navegaciones se desincronicen:
// las dos leen del mismo lugar.
function showView(view) {
  $$("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$("main section").forEach((sec) => {
    sec.classList.toggle("hidden", sec.id !== `view-${view}`);
  });
  window.scrollTo({ top: 0 });
}

function initTabs() {
  // Se ata a [data-view] y no a .tab: antes también se ataba a las pestañas del
  // login y al botón "Salir", que no tienen data-view, así que un click ahí
  // corría showView(undefined) y tapaba todas las secciones.
  $$("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
  initTabs();
  initAuthTabs();
  initFab();
  initSheets();
  $("#auth-form").addEventListener("submit", onSubmitAuth);
  $("#logout-btn").addEventListener("click", onLogout);
  // Los listeners se bindean siempre: el login posterior los necesita.
  $("#period-select").addEventListener("change", (e) => {
    state.period = e.target.value;
    refreshPanel();
  });
  $("#tx-type").addEventListener("change", syncCategoryOptions);
  $("#tx-form").addEventListener("submit", onSubmitTx);
  $("#bill-form").addEventListener("submit", onSubmitBill);
  $("#goal-form").addEventListener("submit", onSubmitGoal);
  $("#budget-form").addEventListener("submit", onSubmitBudget);
  $("#budget-month").addEventListener("change", (e) => {
    state.budgetMonth = e.target.value || currentMonth();
    loadBudgets();
  });
  $("#chat-form").addEventListener("submit", onSubmitChat);

  $("#tx-date").value = new Date().toISOString().slice(0, 10);
  $("#budget-month").value = state.budgetMonth;

  if (!localStorage.getItem(TOKEN_KEY)) {
    showAuth();
    return;
  }
  enterApp();
  try {
    await loadConfig();
    await loadCategories();
    await refreshPanel();
  } catch (err) {
    toast(`No se pudo cargar: ${err.message}`, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
