"""Cálculos de dominio: objetivos de ahorro, presupuestos y alertas.

Existe una sola implementación de cada número, y la comparten la API (que la
devuelve en JSON) y las herramientas del agente (que la devuelven en texto).
Por eso el saldo que ves en la pantalla y el que te dice el asistente no
pueden divergir: salen de la misma función.

Convención: acá abajo todo se maneja en centavos enteros. La conversión a
moneda ocurre una sola vez, al serializar hacia afuera.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Account, Bill, Budget, Category, SavingsGoal, Transaction, Vehicle

# Estados posibles de un presupuesto dentro de su mes.
OK = "ok"
ATENCION = "atencion"
EXCEDIDO = "excedido"

# Tipos de objetivo y cómo se deriva el progreso.
AHORRO = "ahorro"          # suma de todos los movimientos asignados
RECAUDACION = "recaudacion"  # ingresos − gastos asignados

# Estados de un objetivo.
EN_CURSO = "en_curso"
ALCANZADO = "alcanzado"
VENCIDO = "vencido"

# Estados derivados de un vencimiento.
PAGADO = "pagado"
PENDIENTE = "pendiente"
PROXIMO = "proximo"  # vence dentro de la ventana de aviso
BILL_VENCIDO = "vencido"

# Un vencimiento avisa cuando faltan estos días o menos.
BILL_ALERT_DAYS = 7

# Severidades del centro de alertas.
ALTA = "alta"
MEDIA = "media"
BAJA = "baja"

# Tipos de billetera.
BANCO = "banco"
DIGITAL = "digital"
EFECTIVO = "efectivo"
OTRO = "otro"


# ---------------------------------------------------------------------------
# Períodos
# ---------------------------------------------------------------------------

def month_bounds(month: str | None) -> tuple[date, date]:
    """'YYYY-MM' → (primer día, último día). Sin argumento, el mes actual.

    Acepta también 'YYYY-MM-DD' (toma el mes de esa fecha).
    """
    if not month:
        today = date.today()
        year, mon = today.year, today.month
    else:
        parts = str(month).strip().split("-")
        if len(parts) < 2:
            raise ValueError("El mes debe tener formato YYYY-MM (ej: 2026-09).")
        try:
            year, mon = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("El mes debe tener formato YYYY-MM (ej: 2026-09).")
        if not 1 <= mon <= 12:
            raise ValueError(f"Mes inválido: {mon}. Debe ser entre 01 y 12.")
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


# ---------------------------------------------------------------------------
# Objetivos de ahorro
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GoalRow:
    id: int
    name: str
    kind: str  # "ahorro" | "recaudacion"
    target_cents: int
    saved_cents: int
    remaining_cents: int
    percent: float  # 0..100+, puede pasar de 100 si te pasaste del objetivo
    target_date: date | None
    notes: str
    status: str
    required_per_month_cents: int | None  # para llegar a la fecha límite
    contributions: int  # cuántos movimientos están asignados


def _goal_aggregate(db: Session, user_id: int, goal: SavingsGoal) -> tuple[int, int]:
    """(suma en centavos, cantidad de movimientos) de un objetivo.

    - ahorro: suma directa de los montos asignados (los aportes son gastos en
      la cuenta general pero plata que queda en la meta).
    - recaudación: ingresos asignados − gastos asignados (lo que entró de la
      colecta menos lo que ya se pagó con esa plata).
    """
    rows = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user_id, Transaction.goal_id == goal.id
        )
    ).all()
    if goal.kind == RECAUDACION:
        total = sum(
            t.amount_cents if t.type == "income" else -t.amount_cents for t in rows
        )
    else:
        total = sum(t.amount_cents for t in rows)
    return int(total), len(rows)


def goal_contributions(db: Session, user_id: int, goal_id: int) -> tuple[int, int]:
    goal = db.get(SavingsGoal, goal_id)
    if goal is None or goal.user_id != user_id:
        return 0, 0
    return _goal_aggregate(db, user_id, goal)


def _months_until(target: date, today: date) -> float:
    """Meses aprox. que faltan hasta `target` (negativo si ya venció)."""
    return (target.year - today.year) * 12 + (target.month - today.month) + (
        target.day - today.day
    ) / 30.0


def _goal_row(db: Session, user_id: int, goal: SavingsGoal, today: date) -> GoalRow:
    saved, count = _goal_aggregate(db, user_id, goal)
    remaining = max(goal.target_cents - saved, 0)
    percent = (saved / goal.target_cents * 100) if goal.target_cents else 0.0

    required = None
    if saved >= goal.target_cents:
        status = ALCANZADO
    elif goal.target_date and goal.target_date < today:
        status = VENCIDO
    else:
        status = EN_CURSO
        if goal.target_date:
            months = _months_until(goal.target_date, today)
            if months > 0:
                required = round(remaining / months)

    return GoalRow(
        id=goal.id,
        name=goal.name,
        kind=goal.kind if goal.kind in (AHORRO, RECAUDACION) else AHORRO,
        target_cents=goal.target_cents,
        saved_cents=saved,
        remaining_cents=remaining,
        percent=round(percent, 1),
        target_date=goal.target_date,
        notes=goal.notes or "",
        status=status,
        required_per_month_cents=required,
        contributions=count,
    )


def goal_rows(db: Session, user_id: int) -> list[GoalRow]:
    today = date.today()
    goals = db.scalars(
        select(SavingsGoal)
        .where(SavingsGoal.user_id == user_id)
        .order_by(SavingsGoal.id)
    ).all()
    return [_goal_row(db, user_id, g, today) for g in goals]


# ---------------------------------------------------------------------------
# Presupuestos mensuales
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BudgetRow:
    id: int
    category: str
    kind: str
    limit_cents: int           # presupuesto base (fijo)
    effective_limit_cents: int # base + rollover (lo que realmente vale este mes)
    rollover_cents: int        # lo que se arrastra del mes anterior (+ sobra / - falta)
    spent_cents: int
    remaining_cents: int       # negativo si ya se pasó del tope efectivo
    percent: float             # sobre el tope efectivo
    projected_cents: int       # a ritmo actual, cuánto se gastaría al cierre del mes
    status: str
    month: str                 # 'YYYY-MM' al que corresponde este row
    days_left: int


@dataclass(frozen=True)
class AnomalyRow:
    """Gasto que se desvía significativamente del patrón histórico."""
    id: int
    date: date
    description: str
    category: str
    amount_cents: int
    expected_cents: int        # media histórica (meses anteriores)
    deviation_pct: float       # cuánto se desvía: (actual - esperado) / esperado * 100


def budget_status(spent_cents: int, limit_cents: int) -> str:
    if limit_cents <= 0:
        return OK
    pct = spent_cents / limit_cents
    if pct > 1:
        return EXCEDIDO
    if pct >= get_settings().budget_alert_pct:
        return ATENCION
    return OK


def _category_spend(db: Session, user_id: int, category_id: int, start: date, end: date) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.user_id == user_id,
                Transaction.category_id == category_id,
                Transaction.type == "expense",
                Transaction.date >= start,
                Transaction.date <= end,
            )
        )
        or 0
    )


def budget_rows(db: Session, month: str | None = None, user_id: int = 0) -> list[BudgetRow]:
    """Presupuestos con su estado para el mes pedido (por defecto, el actual).

    La proyección solo tiene sentido en el mes en curso: para meses ya
    cerrados el "proyectado" es justamente lo gastado.

    El tope efectivo = presupuesto base + rollover del mes anterior.
    """
    start, end = month_bounds(month)
    today = date.today()
    days_total = (end - start).days + 1
    in_current_month = start <= today <= end
    days_elapsed = (today - start).days + 1 if in_current_month else days_total

    # Para calcular rollover, necesitamos el mes anterior
    prev_start, prev_end = _prev_month_bounds(start)

    rows: list[BudgetRow] = []
    for budget in db.scalars(
        select(Budget)
        .join(Category)
        .where(Budget.user_id == user_id, Category.user_id == user_id)
        .order_by(Category.name)
    ).all():
        spent = _category_spend(db, user_id, budget.category_id, start, end)
        if in_current_month and days_elapsed:
            projected = round(spent * days_total / days_elapsed)
        else:
            projected = spent

        # Rollover: solo si el presupuesto existía en el mes anterior
        # (si se creó este mes, no hay rollover previo)
        from datetime import datetime
        budget_created = budget.created_at.date() if hasattr(budget.created_at, 'date') else budget.created_at
        has_prev_month = budget_created < start

        if has_prev_month:
            prev_spent = _category_spend(db, user_id, budget.category_id, prev_start, prev_end)
            prev_limit = budget.amount_cents + budget.rollover_cents
            rollover = prev_limit - prev_spent  # positivo = sobró, negativo = faltó
        else:
            rollover = 0

        effective_limit = budget.amount_cents + rollover
        rows.append(
            BudgetRow(
                id=budget.id,
                category=budget.category.name,
                kind=budget.category.kind,
                limit_cents=budget.amount_cents,
                effective_limit_cents=effective_limit,
                rollover_cents=rollover,
                spent_cents=spent,
                remaining_cents=effective_limit - spent,
                percent=round(spent / effective_limit * 100, 1) if effective_limit else 0.0,
                projected_cents=projected,
                status=budget_status(spent, effective_limit),
                month=start.strftime("%Y-%m"),
                days_left=max((end - today).days, 0) if in_current_month else 0,
            )
        )
    return rows


def _prev_month_bounds(current_start: date) -> tuple[date, date]:
    """Dado el 1er día del mes actual, devuelve (1er día, último día) del mes anterior."""
    import calendar
    if current_start.month == 1:
        prev_start = date(current_start.year - 1, 12, 1)
    else:
        prev_start = date(current_start.year, current_start.month - 1, 1)
    # último día del mes anterior (usar prev_start, no el mes siguiente)
    last_day = calendar.monthrange(prev_start.year, prev_start.month)[1]
    prev_end = date(prev_start.year, prev_start.month, last_day)
    return prev_start, prev_end


def budget_alerts(rows: list[BudgetRow]) -> list[BudgetRow]:
    """Los presupuestos que requieren atención, del más urgente al menos."""
    order = {EXCEDIDO: 0, ATENCION: 1, OK: 2}
    return sorted(
        (r for r in rows if r.status != OK), key=lambda r: (order[r.status], -r.percent)
    )


# ---------------------------------------------------------------------------
# Detección de anomalías (gastos que se disparan vs histórico)
# ---------------------------------------------------------------------------

def detect_anomalies(db: Session, month: str | None = None, threshold_pct: float = 150.0,
                     user_id: int = 0) -> list[AnomalyRow]:
    """Detecta gastos del mes que superan `threshold_pct`% de la media histórica.

    Compara cada gasto individual del mes contra el promedio de gastos
    de esa misma categoría en meses anteriores (excluyendo el mes actual).
    Solo considera categorías con al menos 3 meses de historial.

    `threshold_pct=150` → avisa si el gasto es > 2.5x la media.
    """
    start, end = month_bounds(month)

    # Obtener todas las categorías de gasto con presupuesto (son las que importan)
    budgets = db.scalars(
        select(Budget)
        .join(Category)
        .where(Budget.user_id == user_id, Category.user_id == user_id)
        .order_by(Category.name)
    ).all()
    if not budgets:
        return []

    # Para cada categoría, calcular la media histórica (meses anteriores)
    cat_avg: dict[int, float] = {}
    cat_months_count: dict[int, int] = {}
    for budget in budgets:
        cat_id = budget.category_id
        # Meses anteriores al actual (máx 12 meses para no ir muy atrás)
        for i in range(1, 13):
            m_start, m_end = _prev_month_bounds(start)
            for _ in range(i - 1):
                m_start, m_end = _prev_month_bounds(m_start)
            spent = _category_spend(db, user_id, cat_id, m_start, m_end)
            if spent > 0:
                cat_avg.setdefault(cat_id, []).append(spent)
        if cat_id in cat_avg and len(cat_avg[cat_id]) >= 3:
            cat_avg[cat_id] = sum(cat_avg[cat_id]) / len(cat_avg[cat_id])
            cat_months_count[cat_id] = len(cat_avg[cat_id])
        else:
            cat_avg.pop(cat_id, None)
            cat_months_count.pop(cat_id, None)

    if not cat_avg:
        return []

    # Ahora revisar cada gasto individual del mes actual
    from sqlalchemy import select as sql_select
    txs = db.scalars(
        sql_select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.category_id.in_(cat_avg.keys()),
        ).order_by(Transaction.date)
    ).all()

    anomalies: list[AnomalyRow] = []
    for tx in txs:
        avg = cat_avg[tx.category_id]
        if avg <= 0:
            continue
        deviation = (tx.amount_cents - avg) / avg * 100.0
        if deviation >= threshold_pct:
            anomalies.append(
                AnomalyRow(
                    id=tx.id,
                    date=tx.date,
                    description=tx.description or "(sin descripción)",
                    category=tx.category.name,
                    amount_cents=tx.amount_cents,
                    expected_cents=round(avg),
                    deviation_pct=round(deviation, 1),
                )
            )

    # Ordenar por desviación descendente (lo más anómalo primero)
    anomalies.sort(key=lambda a: -a.deviation_pct)
    return anomalies


# ---------------------------------------------------------------------------
# Vencimientos
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BillRow:
    id: int
    description: str
    amount_cents: int
    due_date: date
    category: str
    recurrence: str  # "once" | "monthly"
    notes: str
    state: str  # "pagado" | "vencido" | "proximo" | "pendiente"
    days_until: int  # negativo si ya venció


def _bill_row(bill: Bill, today: date) -> BillRow:
    days = (bill.due_date - today).days
    if bill.paid_at is not None:
        state = PAGADO
    elif days < 0:
        state = BILL_VENCIDO
    elif days <= BILL_ALERT_DAYS:
        state = PROXIMO
    else:
        state = PENDIENTE
    return BillRow(
        id=bill.id,
        description=bill.description,
        amount_cents=bill.amount_cents,
        due_date=bill.due_date,
        category=bill.category.name,
        recurrence=bill.recurrence,
        notes=bill.notes or "",
        state=state,
        days_until=days,
    )


def bill_rows(db: Session, user_id: int, solo_pendientes: bool = True) -> list[BillRow]:
    """Vencimientos con su estado derivado, ordenados por fecha.

    Por defecto solo los no pagados (lo que importa en el día a día); con
    `solo_pendientes=False` incluye el historial de pagados.
    """
    today = date.today()
    q = (
        select(Bill)
        .join(Category)
        .where(Bill.user_id == user_id, Category.user_id == user_id)
    )
    if solo_pendientes:
        q = q.where(Bill.paid_at.is_(None))
    bills = db.scalars(q.order_by(Bill.due_date, Bill.id)).all()
    return [_bill_row(b, today) for b in bills]


def add_months(d: date, months: int = 1) -> date:
    """Suma meses cuidando el fin de mes (31/01 + 1 mes → 28/02)."""
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


# ---------------------------------------------------------------------------
# Ingresos del mes (por procedencia y por día)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IncomeRow:
    """Vista de un ingreso para la tarjeta «Ingresos del mes»."""
    id: int
    date: date
    amount_cents: int
    category: str
    source: str  # "(sin procedencia)" si viene vacío
    description: str


def income_rows(db: Session, user_id: int, month: str | None = None) -> list[IncomeRow]:
    """Ingresos del mes pedido (por defecto, el actual), más viejos primero."""
    start, end = month_bounds(month)
    txs = db.scalars(
        select(Transaction)
        .join(Category)
        .where(
            Transaction.user_id == user_id,
            Category.user_id == user_id,
            Transaction.type == "income",
            Transaction.date >= start,
            Transaction.date <= end,
        ).order_by(Transaction.date, Transaction.id)
    ).all()
    return [
        IncomeRow(
            id=t.id,
            date=t.date,
            amount_cents=t.amount_cents,
            category=t.category.name,
            source=(t.source or "").strip() or "(sin procedencia)",
            description=t.description or "",
        )
        for t in txs
    ]


# ---------------------------------------------------------------------------
# Billeteras (patrimonio: la plata que hay, no la que pasó)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccountRow:
    id: int
    name: str
    kind: str  # "banco" | "digital" | "efectivo" | "otro"
    apertura_cents: int  # saldo de partida (lo que había al cargarla)
    balance_cents: int  # derivado: apertura + movimientos de la billetera
    movimientos: int  # cuántos movimientos tiene imputados
    ultimo_movimiento: date | None
    notes: str
    updated_at: datetime | None


def _neto_por_cuenta(db: Session, user_id: int) -> dict[int, tuple[int, int, date | None]]:
    """Neto (ingresos − gastos), cantidad y última fecha, agrupado por billetera.

    Una sola consulta para todas las billeteras: son miles de filas y esto se
    recalcula en cada refresh del panel.
    """
    filas = db.execute(
        select(
            Transaction.cuenta_id,
            func.sum(
                case(
                    (Transaction.type == "income", Transaction.amount_cents),
                    else_=-Transaction.amount_cents,
                )
            ),
            func.count(Transaction.id),
            func.max(Transaction.date),
        )
        .where(Transaction.user_id == user_id, Transaction.cuenta_id.isnot(None))
        .group_by(Transaction.cuenta_id)
    ).all()
    return {
        cuenta_id: (int(neto or 0), int(cantidad or 0), ultimo)
        for cuenta_id, neto, cantidad, ultimo in filas
    }


def account_rows(db: Session, user_id: int) -> list[AccountRow]:
    """Billeteras del usuario con su saldo DERIVADO, de mayor a menor.

    El saldo sale de `apertura_cents + Σ movimientos` (ver `models.Account`): se
    mantiene solo a medida que se registran cobros y gastos, sin tener que
    actualizar N billeteras a mano. Lo consumen la tarjeta del panel
    (`GET /api/accounts`) y la herramienta `listar_billeteras` del agente, así
    que el número de la pantalla y el del chat no pueden divergir.
    """
    por_cuenta = _neto_por_cuenta(db, user_id)
    accounts = db.scalars(select(Account).where(Account.user_id == user_id)).all()
    rows = [
        AccountRow(
            id=a.id,
            name=a.name,
            kind=a.kind if a.kind in (BANCO, DIGITAL, EFECTIVO, OTRO) else OTRO,
            apertura_cents=a.apertura_cents,
            balance_cents=a.apertura_cents + por_cuenta.get(a.id, (0, 0, None))[0],
            movimientos=por_cuenta.get(a.id, (0, 0, None))[1],
            ultimo_movimiento=por_cuenta.get(a.id, (0, 0, None))[2],
            notes=a.notes or "",
            updated_at=a.updated_at,
        )
        for a in accounts
    ]
    rows.sort(key=lambda r: (-r.balance_cents, r.name))
    return rows


def total_cents(db: Session, user_id: int) -> int:
    """Patrimonio total: la suma de los saldos de todas las billeteras."""
    return sum(r.balance_cents for r in account_rows(db, user_id))


@dataclass(frozen=True)
class Comprometido:
    """Plata que ya sabés que tenés que pagar, según los vencimientos.

    Son cuatro montos y dos conteos porque cada uno contesta una pregunta
    distinta:
    - `total_cents`: cuánto debés en total (vencido + futuro). Es contra este
      número contra el que hay que mirar "disponible".
    - `mes_cents`: cuánto se va este mes calendario.
    - `vencidos_cents`: lo que ya venció y todavía no pagaste (lo urgente).
    - `disponible_cents`: patrimonio − lo comprometido. El único número que
      contesta "¿puedo gastar esto?".

    Los `count` van porque el monto solo no alcanza: 450.000 comprometidos son
    una cosa si es un pago y otra si son cinco, y el usuario decide distinto.

    Vive acá y no en cada pantalla porque el agente y el panel tienen que dar
    el mismo disponible: si lo calcularan por su cuenta, un día divergen.
    """

    total_cents: int
    mes_cents: int
    vencidos_cents: int
    disponible_cents: int
    count: int
    vencidos_count: int


def comprometido(db: Session, user_id: int) -> Comprometido:
    """Suma los vencimientos impagos y descuenta lo que ya no está disponible.

    A diferencia del resto del resumen, esto NO tiene período: un vencimiento no
    "es de este mes" o "de este año", vence en una fecha. Por eso los callers lo
    tratan aparte del filtro de fechas de los movimientos.
    """
    hoy = date.today()
    filas = bill_rows(db, user_id)
    total = sum(f.amount_cents for f in filas)
    mes = sum(f.amount_cents for f in filas if f.due_date.year == hoy.year and f.due_date.month == hoy.month)
    return Comprometido(
        total_cents=total,
        mes_cents=mes,
        vencidos_cents=sum(f.amount_cents for f in filas if f.days_until < 0),
        # Puede dar negativo si debés más de lo que tenés: es la verdad, y
        # por eso el disponible se muestra con signo.
        disponible_cents=total_cents(db, user_id) - total,
        count=len(filas),
        vencidos_count=sum(1 for f in filas if f.days_until < 0),
    )


def reconcile_account(db: Session, acc: Account, declarado_cents: int, user_id: int) -> int:
    """Fija la apertura para que el saldo DERIVADO sea el saldo real declarado.

    Es una conciliación, no una corrección de historia: el movimiento que te
    faltó no se inventa, sólo deja de desfasar el total. Devuelve la apertura
    nueva (queda negativa si declarás un saldo menor que lo ya movido).
    """
    neto = _neto_por_cuenta(db, user_id).get(acc.id, (0, 0, None))[0]
    acc.apertura_cents = declarado_cents - neto
    db.commit()
    db.refresh(acc)
    return acc.apertura_cents


# ---------------------------------------------------------------------------
# Centro de alertas (una sola fuente para el panel y el agente)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AlertRow:
    severity: str  # "alta" | "media" | "baja"
    kind: str  # "vencimiento" | "presupuesto" | "objetivo" | "anomalia"
    message: str


def all_alerts(db: Session, user_id: int) -> list[AlertRow]:
    """Consolida todo lo que requiere atención, lo más urgente primero.

    La comparten el banner del panel (`GET /api/alerts`) y el agente
    (`listar_alertas`): no hay dos cálculos que puedan discrepar.
    """
    # Import diferido: fmt vive en la capa de herramientas (que consume este
    # módulo), así evitamos un import circular a nivel de módulo. Los montos
    # se formatean igual que en el resto de las respuestas del agente.
    from .agent.tools.base import fmt

    alerts: list[AlertRow] = []
    today = date.today()

    # 1. Vencimientos: vencidos (alta) y próximos (media).
    for b in bill_rows(db, user_id):
        if b.state == BILL_VENCIDO:
            alerts.append(AlertRow(
                ALTA, "vencimiento",
                f"🔴 Venció hace {-b.days_until} día(s): «{b.description}» "
                f"por {fmt(b.amount_cents)} ({b.category}).",
            ))
        elif b.state == PROXIMO:
            alerts.append(AlertRow(
                MEDIA, "vencimiento",
                f"🟡 Vence en {b.days_until} día(s) ({b.due_date.isoformat()}): "
                f"«{b.description}» por {fmt(b.amount_cents)} ({b.category}).",
            ))

    # 2. Presupuestos del mes en curso.
    for r in budget_alerts(budget_rows(db, None, user_id)):
        if r.status == EXCEDIDO:
            alerts.append(AlertRow(
                ALTA, "presupuesto",
                f"🔴 {r.category} excedido: gastado {fmt(r.spent_cents)} "
                f"de {fmt(r.effective_limit_cents)}.",
            ))
        else:
            alerts.append(AlertRow(
                MEDIA, "presupuesto",
                f"🟡 {r.category} al {r.percent:.0f}% del presupuesto "
                f"(quedan {fmt(r.remaining_cents)}, faltan {r.days_left} días).",
            ))

    # 3. Objetivos: vencidos (alta) y con fecha dentro de 30 días sin alcanzar (media).
    for g in goal_rows(db, user_id):
        if g.status == VENCIDO:
            alerts.append(AlertRow(
                ALTA, "objetivo",
                f"🔴 El objetivo «{g.name}» venció sin completarse "
                f"({fmt(g.saved_cents)} de {fmt(g.target_cents)}).",
            ))
        elif (g.status == EN_CURSO and g.target_date
                and 0 <= (g.target_date - today).days <= 30):
            alerts.append(AlertRow(
                MEDIA, "objetivo",
                f"🟡 «{g.name}» vence el {g.target_date.isoformat()}: "
                f"faltan {fmt(g.remaining_cents)}.",
            ))

    # 4. Anomalías del mes (media, resumidas en una línea).
    anomalies = detect_anomalies(db, None, 150.0, user_id)
    if anomalies:
        top = anomalies[0]
        alerts.append(AlertRow(
            MEDIA, "anomalia",
            f"🟡 {len(anomalies)} gasto(s) fuera de lo habitual; el mayor: "
            f"«{top.description}» en {top.category} (+{top.deviation_pct:.0f}% "
            f"sobre su media).",
        ))

    order = {ALTA: 0, MEDIA: 1, BAJA: 2}
    return sorted(alerts, key=lambda a: (order[a.severity], a.kind))
