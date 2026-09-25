/* Finanzas Personales — lógica del frontend */

"use strict";

const state = {
  currency: "ARS",
  provider: "mock",
  model: "mock",
  sensitiveAmount: 50000,
  period: "mes",
  categories: [],
  pending: null,
  chatMessages: [], // historial {role, content} enviado al backend
};

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);

function moneyFmt(amount) {
  // La API devuelve montos en unidades de moneda (floats); acá solo se formatean.
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: state.currency,
    maximumFractionDigits: 2,
  }).format(amount);
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

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) { /* sin cuerpo JSON */ }
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
  if (state.provider === "mock") {
    $("#chat-fallback").classList.remove("hidden");
  }
}

async function loadCategories() {
  const cats = await api("/api/categories");
  state.categories = cats;
  const select = $("#tx-category");
  const prev = select.value;
  select.innerHTML = "";
  for (const c of cats) {
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
    const pct = Math.round((c.total / max) * 100);
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <div class="bar-top"><span>${esc(c.category)}</span><span class="num">${moneyFmt(c.total)}</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>`;
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
    tr.innerHTML = `
      <td>${esc(t.date)}</td>
      <td>${esc(t.category)}</td>
      <td>${esc(t.description || "—")}</td>
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

async function refreshPanel() {
  await Promise.all([renderSummary(), renderTransactions()]);
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
    description: $("#tx-description").value.trim(),
    date: $("#tx-date").value || null,
  };
  setBusy(btn, true);
  try {
    await api("/api/transactions", { method: "POST", body: JSON.stringify(payload) });
    toast("Movimiento registrado", "success");
    e.target.reset();
    document.getElementById("tx-date").value = new Date().toISOString().slice(0, 10);
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
      bubble.textContent = res.reply;
      bubble.innerHTML = esc(res.reply);
      state.chatMessages.push({ role: "assistant", content: res.reply });
    } else {
      bubble.remove();
    }
    handleAgentResponse(res);
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
// Tabs
// ---------------------------------------------------------------------------

function initTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      $("#view-panel").classList.toggle("hidden", btn.dataset.view !== "panel");
      $("#view-agent").classList.toggle("hidden", btn.dataset.view !== "agent");
    });
  });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
  initTabs();
  $("#period-select").addEventListener("change", (e) => {
    state.period = e.target.value;
    refreshPanel();
  });
  $("#tx-form").addEventListener("submit", onSubmitTx);
  $("#chat-form").addEventListener("submit", onSubmitChat);

  $("#tx-date").value = new Date().toISOString().slice(0, 10);

  try {
    await loadConfig();
    await loadCategories();
    await refreshPanel();
  } catch (err) {
    toast(`No se pudo cargar: ${err.message}`, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);