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
  budgetMonth: currentMonth(),
  pending: null,
  chatMessages: [], // historial {role, content} enviado al backend
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
function syncCategoryOptions() {
  const select = $("#tx-category");
  const prev = select.value;
  const kind = $("#tx-type").value;
  select.innerHTML = "";
  for (const c of state.categories) {
    if (c.kind !== kind) continue;
    const opt = document.createElement("option");
    opt.value = c.name;
    opt.textContent = c.name;
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === prev)) select.value = prev;
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

async function renderSummary() {
  const range = periodRange();
  const qs = new URLSearchParams(range).toString();
  const s = await api(`/api/summary?${qs}`);
  $("#sum-balance").textContent = moneyFmt(s.balance);
  $("#sum-balance").parentElement.classList.toggle("pos", s.balance >= 0);
  $("#sum-balance").parentElement.classList.toggle("neg", s.balance < 0);
  $("#sum-income").textContent = moneyFmt(s.total_income);
  $("#sum-expense").textContent = moneyFmt(s.total_expense);
  $("#sum-count").textContent = s.count;
  $("#period-info").textContent = `Período: ${s.period}`;

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

async function renderTransactions() {
  const range = periodRange();
  const qs = new URLSearchParams({ ...range, limite: "30" }).toString();
  const rows = await api(`/api/transactions?${qs}`);
  const tbody = $("#tx-tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">Sin movimientos en este período.</td></tr>`;
    return;
  }
  tbody.innerHTML = "";
  for (const t of rows) {
    const tr = document.createElement("tr");
    const isIncome = t.type === "income";
    const goal = t.goal ? `<span class="tag goal" title="Aporte a un objetivo">🎯 ${esc(t.goal)}</span>` : "";
    tr.innerHTML = `
      <td>${esc(t.date)}</td>
      <td>${esc(t.category)}</td>
      <td>${esc(t.description || "—")} ${goal}</td>
      <td><span class="tag ${t.type}">${isIncome ? "Ingreso" : "Gasto"}</span></td>
      <td class="num ${isIncome ? "pos" : "neg"}">${moneyFmt(t.amount)}</td>
      <td><button class="btn ghost small-btn" data-del="${t.id}" title="Eliminar">✕</button></td>`;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar la transacción #${btn.dataset.del}?`)) return;
      try {
        await api(`/api/transactions/${btn.dataset.del}`, { method: "DELETE" });
        toast("Transacción eliminada", "success");
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

async function refreshPanel() {
  // allSettled y no all: si un endpoint falla, el resto del panel tiene que
  // seguir mostrando algo. Con Promise.all, un solo fallo dejaba el panel a
  // medio cargar sin explicar por qué.
  const tareas = [
    ["resumen", renderSummary],
    ["movimientos", renderTransactions],
    ["objetivos", loadGoals],
    ["presupuestos", loadBudgets],
    ["vencimientos", loadBills],
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

// ---------------------------------------------------------------------------
// Objetivos de ahorro
// ---------------------------------------------------------------------------

async function loadGoals() {
  state.goals = await api("/api/goals");
  // El selector del formulario de movimiento
  const select = $("#tx-goal");
  const prev = select.value;
  select.innerHTML = `<option value="">— sin objetivo —</option>`;
  for (const g of state.goals) {
    const opt = document.createElement("option");
    opt.value = g.name;
    opt.textContent = g.name;
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
    el.innerHTML = `
      <div class="goal-head">
        <div>
          <div class="goal-name">${esc(g.name)}</div>
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

function renderBudgets(rows) {
  const box = $("#budgets-list");
  if (!rows.length) {
    box.innerHTML = `<div class="no-data">No hay presupuestos cargados para este mes.</div>`;
    return;
  }
  box.innerHTML = "";
  for (const b of rows) {
    const el = document.createElement("div");
    el.className = `budget-card ${b.status}`;
    const partes = [];
    if (b.remaining_cents < 0) partes.push(`te pasaste por ${moneyFmt(Math.abs(b.remaining))}`);
    else partes.push(`quedan ${moneyFmt(b.remaining)}`);
    if (b.days_left) partes.push(`faltan ${b.days_left} días`);
    if (b.projected_cents > b.limit_cents && b.status !== "excedido") {
      partes.push(`a este ritmo terminás el mes en ${moneyFmt(b.projected)}`);
    }
    const icon = b.status === "excedido" ? "🔴" : b.status === "atencion" ? "🟡" : "🟢";
    el.innerHTML = `
      <div class="goal-head">
        <div>
          <div class="goal-name">${icon} ${esc(b.category)}</div>
          <div class="muted small">${partes.map(esc).join(" · ")}</div>
        </div>
        <button class="btn ghost small-btn" data-del-budget="${b.id}" title="Eliminar presupuesto">✕</button>
      </div>
      <div class="bar-track goal-track">
        <div class="bar-fill" style="width:${Math.min(b.percent, 100)}%"></div>
      </div>
      <div class="bar-top">
        <span class="num"><strong>${moneyFmt(b.spent)}</strong> de ${moneyFmt(b.limit)}</span>
        <span class="muted">${pct(b.percent)}</span>
      </div>`;
    box.appendChild(el);
  }
  box.querySelectorAll("[data-del-budget]").forEach((btn) => {
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
  box.innerHTML = "";
  for (const b of rows) {
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
  const payload = {
    type: $("#tx-type").value,
    amount,
    category: $("#tx-category").value,
    goal: $("#tx-goal").value || null,
    description: $("#tx-description").value.trim(),
    date: $("#tx-date").value || null,
  };
  setBusy(btn, true);
  try {
    await api("/api/transactions", { method: "POST", body: JSON.stringify(payload) });
    toast("Movimiento registrado", "success");
    e.target.reset();
    syncCategoryOptions();
    $("#tx-date").value = new Date().toISOString().slice(0, 10);
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
}

function enterApp(username) {
  $("#auth-screen").classList.add("hidden");
  $("#main-container").classList.remove("hidden");
  $("#user-box").classList.remove("hidden");
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
// Tabs
// ---------------------------------------------------------------------------

function initTabs() {
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      $$("main section").forEach((sec) => {
        sec.classList.toggle("hidden", sec.id !== `view-${btn.dataset.view}`);
      });
    });
  });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
  initTabs();
  initAuthTabs();
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
