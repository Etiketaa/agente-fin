"""Endpoints REST de la aplicación."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from . import analytics, auth as auth_helpers, freno
from .agent.agent import run_agent
from .agent.provider import ProviderError, get_provider
from .agent.tools import cents_to_money, money_to_cents
from .config import get_settings
from .db import get_db
from .models import Account, Bill, Budget, Category, SavingsGoal, Transaction, User, UserSession
from .seed import DEFAULT_ACCOUNT_NAME, default_account
from .schemas import (
    AccountCreate,
    AccountsOut,
    AccountUpdate,
    AccountOut,
    AgentChatRequest,
    AgentConfirmRequest,
    AgentResponse,
    AlertOut,
    BillCreate,
    BillOut,
    BillPayOut,
    BudgetCreate,
    BudgetOut,
    CategoryOut,
    CategoryTotal,
    GoalCreate,
    GoalOut,
    IncomeDay,
    IncomeMonthOut,
    IncomeSourceTotal,
    LoginRequest,
    RegisterRequest,
    SummaryOut,
    TokenOut,
    TransactionCreate,
    TransactionOut,
    UserOut,
)

router = APIRouter(prefix="/api")


def _parse_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"Fecha inválida: '{value}'. Usá YYYY-MM-DD.")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """El usuario dueño del token Bearer. Todo endpoint de datos lo exige.

    Devuelve 401 sin distinguir "sin token" de "token inválido": no filtramos
    información sobre sesiones. Además completa las categorías si el usuario
    todavía no tiene (repara altas creadas antes del seed por usuario).
    """
    user = _user_from_request(request, db)
    if user is None:
        raise HTTPException(401, "Sesión inválida o ausente. Iniciá sesión de nuevo.")
    from .seed import seed_user_categories

    seed_user_categories(db, user)
    return user


def _find_category(db: Session, user_id: int, name: str, kind: str | None = None) -> Category:
    cat = db.scalar(
        select(Category).where(
            Category.user_id == user_id,
            func.lower(Category.name) == name.strip().lower(),
        )
    )
    if cat is None:
        raise HTTPException(404, f"Categoría no encontrada: {name}")
    if kind and cat.kind != kind:
        raise HTTPException(400, f"La categoría '{cat.name}' es de {cat.kind}, no de {kind}")
    return cat


def _find_account(db: Session, user_id: int, name: str | None) -> Account:
    """Resuelve la billetera de un movimiento.

    Sin nombre (o vacío) cae en «General»: el patrimonio total no puede perder
    plata, así que ningún movimiento queda fuera de una billetera. Si el nombre
    no existe es un error del cliente (400), no un silencio.
    """
    if name and name.strip() and name.strip() != DEFAULT_ACCOUNT_NAME:
        acc = db.scalar(
            select(Account).where(
                Account.user_id == user_id,
                func.lower(Account.name) == name.strip().lower(),
            )
        )
        if acc is None:
            nombres = ", ".join(
                a.name for a in db.scalars(
                    select(Account).where(Account.user_id == user_id).order_by(Account.name)
                ).all()
            )
            raise HTTPException(400, f"No existe la billetera '{name}'. Tenés: {nombres}")
        return acc
    return default_account(db, user_id)


def _owned(db: Session, model, oid: int, user_id: int, label: str):
    """db.get + chequeo de dueño. Si no es tuyo, 404 (no 403): no filtramos
    ni siquiera la existencia de registros ajenos."""
    row = db.get(model, oid)
    if row is None or row.user_id != user_id:
        raise HTTPException(404, f"No existe {label} #{oid}")
    return row


def _to_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        type=t.type,
        amount=cents_to_money(t.amount_cents),
        amount_cents=t.amount_cents,
        category=t.category.name,
        description=t.description,
        date=t.date,
        goal=t.goal.name if t.goal else None,
        source=t.source,
        cuenta=t.account.name if t.account else None,
    )


def _goal_out(row: analytics.GoalRow) -> GoalOut:
    return GoalOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        target_amount=cents_to_money(row.target_cents),
        target_amount_cents=row.target_cents,
        saved=cents_to_money(row.saved_cents),
        saved_cents=row.saved_cents,
        remaining=cents_to_money(row.remaining_cents),
        remaining_cents=row.remaining_cents,
        percent=row.percent,
        target_date=row.target_date,
        notes=row.notes,
        status=row.status,
        required_per_month=(
            cents_to_money(row.required_per_month_cents)
            if row.required_per_month_cents is not None
            else None
        ),
        required_per_month_cents=row.required_per_month_cents,
        contributions=row.contributions,
        income=cents_to_money(row.income_cents),
        income_cents=row.income_cents,
        expense=cents_to_money(row.expense_cents),
        expense_cents=row.expense_cents,
    )


def _budget_out(row: analytics.BudgetRow) -> BudgetOut:
    return BudgetOut(
        id=row.id,
        category=row.category,
        limit=cents_to_money(row.limit_cents),
        limit_cents=row.limit_cents,
        effective_limit=cents_to_money(row.effective_limit_cents),
        effective_limit_cents=row.effective_limit_cents,
        rollover=cents_to_money(row.rollover_cents),
        rollover_cents=row.rollover_cents,
        spent=cents_to_money(row.spent_cents),
        spent_cents=row.spent_cents,
        remaining=cents_to_money(row.remaining_cents),
        remaining_cents=row.remaining_cents,
        percent=row.percent,
        projected=cents_to_money(row.projected_cents),
        projected_cents=row.projected_cents,
        status=row.status,
        month=row.month,
        days_left=row.days_left,
    )


@router.get("/config")
def get_config():
    s = get_settings()
    provider = get_provider()
    return {
        "currency": s.currency,
        "provider": s.llm_provider,
        "model": provider.model,
        "sensitive_amount": s.sensitive_amount,
        "budget_alert_pct": s.budget_alert_pct,
    }


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

def _issue_token(db: Session, user: User) -> TokenOut:
    """Emite un token de sesión con fecha de vencimiento.

    También barre las sesiones vencidas del usuario antes de guardar la nueva: es
    el único momento donde ya sabemos que el login fue legítimo, así que es un
    lugar seguro para limpiar, y evita que la tabla crezca con filas muertas de
    gente que nunca vuelve a hacer logout.
    """
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.expires_at.is_not(None),
            UserSession.expires_at <= datetime.now(),
        )
    )
    token = auth_helpers.new_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=auth_helpers.hash_token(token),
            expires_at=auth_helpers.session_expiry(get_settings().session_ttl_days),
        )
    )
    db.commit()
    return TokenOut(token=token, username=user.username)


@router.post("/auth/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Crea un usuario y devuelve un token de sesión.

    Todavía no scopea datos (eso llega con el user_id): en este punto solo
    verifica que el flujo de alta y login funcione de punta a punta.
    """
    try:
        username = auth_helpers.valid_username(payload.username)
        auth_helpers.valid_password(payload.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, f"El usuario '{username}' ya existe.")
    user = User(username=username, password_hash=auth_helpers.hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    from .seed import seed_user_categories

    seed_user_categories(db, user)
    return _issue_token(db, user)


@router.post("/auth/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    clave = freno.clave_de(payload.username)
    # El freno va primero y cuenta sólo fallos: quien sabe la clave pasa igual,
    # así que un login legítimo nunca gasta intentos.
    freno.verificar(db, clave)
    try:
        username = auth_helpers.valid_username(payload.username)
    except ValueError:
        freno.registrar_fallo(db, clave)
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not auth_helpers.verify_password(payload.password, user.password_hash):
        # Mismo mensaje en ambos casos: no filtramos si el usuario existe.
        freno.registrar_fallo(db, clave)
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    freno.limpiar(db, clave)
    return _issue_token(db, user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    session = _session_from_request(request, db)
    if session is not None:
        db.delete(session)
        db.commit()
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserOut)
def me(request: Request, db: Session = Depends(get_db)):
    user = _user_from_request(request, db)
    if user is None:
        raise HTTPException(401, "Sesión inválida o ausente. Iniciá sesión de nuevo.")
    return UserOut(id=user.id, username=user.username)


def _token_from_header(request: Request) -> str | None:
    value = request.headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _session_from_request(request: Request, db: Session) -> UserSession | None:
    """La sesión del token Bearer, o None si no hay una válida.

    Este es el único lugar donde se decide si una sesión sirve. Todo lo demás
    (los endpoints de datos, el logout, el `me`) pasa por acá, así que el
    vencimiento se chequea en un solo punto y no se puede olvidar en uno.

    Dos reglas, y la segunda es la importante:
    - Sin `expires_at` la sesión se considera VENCIDA, no válida. Ninguna sesión
      emitida por esta versión queda sin fecha, pero si alguna llegara sin ella
      (una base migrada a mano, un import viejo) se rechaza: un control de
      seguridad que falla abierto no es un control.
    - Una sesión vencida se borra, no se ignora. La fila no sirve para nada más y
      dejarla ocupando lugar haría que el mismo token siga "en la base" para
      siempre, que es justamente lo que se vino a evitar.
    """
    token = _token_from_header(request)
    if not token:
        return None
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == auth_helpers.hash_token(token))
    )
    if session is None:
        return None
    if session.expires_at is None or session.expires_at <= datetime.now():
        db.delete(session)
        db.commit()
        return None
    return session


def _user_from_request(request: Request, db: Session) -> User | None:
    session = _session_from_request(request, db)
    if session is None:
        return None
    return db.get(User, session.user_id)


# ---------------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------------

@router.get("/categories", response_model=list[CategoryOut])
def list_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Category)
        .where(Category.user_id == user.id)
        .order_by(Category.kind, Category.name)
    ).all()


# ---------------------------------------------------------------------------
# Objetivos de ahorro
# ---------------------------------------------------------------------------

@router.get("/goals", response_model=list[GoalOut])
def list_goals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_goal_out(r) for r in analytics.goal_rows(db, user.id)]


@router.post("/goals", response_model=GoalOut, status_code=201)
def create_goal(payload: GoalCreate, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    nombre = payload.name.strip()
    if not nombre:
        raise HTTPException(400, "El nombre del objetivo no puede estar vacío.")
    if db.scalar(
        select(SavingsGoal).where(
            SavingsGoal.user_id == user.id, SavingsGoal.name.ilike(nombre)
        )
    ):
        raise HTTPException(409, f"Ya existe un objetivo llamado '{nombre}'.")
    if payload.target_date and payload.target_date < date.today():
        raise HTTPException(400, f"La fecha límite {payload.target_date} ya pasó.")
    goal = SavingsGoal(
        user_id=user.id,
        name=nombre,
        target_cents=money_to_cents(payload.target_amount),
        target_date=payload.target_date,
        kind=payload.kind,
        notes=payload.notes.strip(),
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    row = next(r for r in analytics.goal_rows(db, user.id) if r.id == goal.id)
    return _goal_out(row)


@router.delete("/goals/{gid}", status_code=204)
def delete_goal(gid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goal = _owned(db, SavingsGoal, gid, user.id, "el objetivo")
    _, count = analytics.goal_contributions(db, user.id, gid)
    if count:
        # Desvincular en silencio dejaría movimientos apuntando a un objetivo
        # inexistente: preferimos rechazar que perder trazabilidad del dinero.
        raise HTTPException(
            409,
            f"El objetivo «{goal.name}» tiene {count} movimiento(s) asignado(s). "
            f"Eliminá o reasigná esos movimientos antes de borrar el objetivo.",
        )
    db.delete(goal)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Presupuestos mensuales
# ---------------------------------------------------------------------------

@router.get("/budgets", response_model=list[BudgetOut])
def list_budgets(mes: Optional[str] = None, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    try:
        rows = analytics.budget_rows(db, mes, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return [_budget_out(r) for r in rows]


@router.post("/budgets", response_model=BudgetOut, status_code=201)
def upsert_budget(payload: BudgetCreate, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    cat = _find_category(db, user.id, payload.category, "expense")
    cents = money_to_cents(payload.amount)
    budget = db.scalar(
        select(Budget).where(Budget.user_id == user.id, Budget.category_id == cat.id)
    )
    if budget is None:
        budget = Budget(user_id=user.id, category_id=cat.id, amount_cents=cents)
        db.add(budget)
        db.commit()
        db.refresh(budget)
    else:
        budget.amount_cents = cents
        db.commit()
    row = next(r for r in analytics.budget_rows(db, None, user.id) if r.id == budget.id)
    return _budget_out(row)


@router.delete("/budgets/{bid}", status_code=204)
def delete_budget(bid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    budget = _owned(db, Budget, bid, user.id, "el presupuesto")
    db.delete(budget)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Vencimientos
# ---------------------------------------------------------------------------

def _bill_out(row: analytics.BillRow, paid_at=None) -> BillOut:
    return BillOut(
        id=row.id,
        description=row.description,
        amount=cents_to_money(row.amount_cents),
        amount_cents=row.amount_cents,
        due_date=row.due_date,
        category=row.category,
        recurrence=row.recurrence,
        notes=row.notes,
        state=row.state,
        days_until=row.days_until,
        paid_at=paid_at,
    )


@router.get("/bills", response_model=list[BillOut])
def list_bills(todos: int = 0, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    bills = {
        b.id: b
        for b in db.scalars(select(Bill).where(Bill.user_id == user.id)).all()
    }
    return [
        _bill_out(r, paid_at=bills[r.id].paid_at)
        for r in analytics.bill_rows(db, user.id, solo_pendientes=not todos)
    ]


@router.post("/bills", response_model=BillOut, status_code=201)
def create_bill(payload: BillCreate, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    descripcion = payload.description.strip()
    if not descripcion:
        raise HTTPException(400, "La descripción del vencimiento no puede estar vacía.")
    cat = _find_category(db, user.id, payload.category, "expense")
    if payload.recurrence not in ("once", "monthly"):
        raise HTTPException(400, "La recurrencia debe ser 'once' o 'monthly'.")
    bill = Bill(
        user_id=user.id,
        description=descripcion,
        amount_cents=money_to_cents(payload.amount),
        due_date=payload.due_date,
        category_id=cat.id,
        recurrence=payload.recurrence,
        notes=payload.notes.strip(),
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    row = next(
        r for r in analytics.bill_rows(db, user.id, solo_pendientes=False) if r.id == bill.id
    )
    return _bill_out(row)


@router.post("/bills/{bid}/pay", response_model=BillPayOut)
def pay_bill(bid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Marca un vencimiento como pagado y genera el gasto correspondiente.

    Si el vencimiento es mensual, además crea el siguiente (misma fecha del
    mes que viene) para no tener que cargarlo a mano cada mes.
    """
    bill = _owned(db, Bill, bid, user.id, "el vencimiento")
    if bill.paid_at is not None:
        raise HTTPException(409, f"El vencimiento «{bill.description}» ya está pagado.")

    t = Transaction(
        user_id=user.id,
        type="expense",
        amount_cents=bill.amount_cents,
        category_id=bill.category_id,
        description=f"Pago: {bill.description}",
        date=date.today(),
        cuenta_id=_find_account(db, user.id, None).id,
    )
    db.add(t)
    bill.paid_at = date.today()

    next_row = None
    next_bill = None
    if bill.recurrence == "monthly":
        next_bill = Bill(
            user_id=user.id,
            description=bill.description,
            amount_cents=bill.amount_cents,
            due_date=analytics.add_months(bill.due_date),
            category_id=bill.category_id,
            recurrence="monthly",
            notes=bill.notes,
        )
        db.add(next_bill)
    db.commit()
    db.refresh(t)
    db.refresh(bill)
    if next_bill is not None:
        db.refresh(next_bill)
        next_row = next(
            r for r in analytics.bill_rows(db, user.id, solo_pendientes=False)
            if r.id == next_bill.id
        )

    row = next(
        r for r in analytics.bill_rows(db, user.id, solo_pendientes=False) if r.id == bill.id
    )
    return BillPayOut(
        bill=_bill_out(row, paid_at=bill.paid_at),
        transaction_id=t.id,
        next_bill=_bill_out(next_row, paid_at=None) if next_row else None,
    )


@router.delete("/bills/{bid}", status_code=204)
def delete_bill(bid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bill = _owned(db, Bill, bid, user.id, "el vencimiento")
    db.delete(bill)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Billeteras (patrimonio: la plata que hay hoy, no la que pasó)
# ---------------------------------------------------------------------------

def _account_out(row: analytics.AccountRow) -> AccountOut:
    return AccountOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        es_default=row.name == DEFAULT_ACCOUNT_NAME,
        apertura=cents_to_money(row.apertura_cents),
        apertura_cents=row.apertura_cents,
        balance=cents_to_money(row.balance_cents),
        balance_cents=row.balance_cents,
        movimientos=row.movimientos,
        ultimo_movimiento=(
            row.ultimo_movimiento.isoformat() if row.ultimo_movimiento else None
        ),
        notes=row.notes,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _account_row(db: Session, user_id: int, aid: int) -> analytics.AccountRow:
    for r in analytics.account_rows(db, user_id):
        if r.id == aid:
            return r
    raise HTTPException(404, f"No existe la billetera #{aid}")


@router.get("/accounts", response_model=AccountsOut)
def list_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Billeteras + patrimonio total.

    El saldo de cada una es derivado (apertura + movimientos) y el total sale de
    la misma función que consume el agente: el número de la pantalla y el del
    chat no pueden divergir.
    """
    rows = analytics.account_rows(db, user.id)
    total = analytics.total_cents(db, user.id)
    return AccountsOut(
        accounts=[_account_out(r) for r in rows],
        total=cents_to_money(total),
        total_cents=total,
        count=len(rows),
    )


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Crea una billetera. `saldo` es el saldo REAL que tiene hoy: queda como
    apertura y de ahí en adelante se mueve sola con cada movimiento."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "El nombre de la billetera no puede estar vacío.")
    if name.lower() == DEFAULT_ACCOUNT_NAME.lower():
        raise HTTPException(
            409, f"«{DEFAULT_ACCOUNT_NAME}» ya existe: es la billetera donde caen los "
                 "movimientos sin asignar."
        )
    existe = db.scalar(
        select(Account).where(
            Account.user_id == user.id, func.lower(Account.name) == name.lower()
        )
    )
    if existe:
        raise HTTPException(409, f"Ya tenés una billetera llamada '{name}'.")
    acc = Account(
        user_id=user.id,
        name=name,
        kind=payload.kind,
        apertura_cents=money_to_cents(payload.saldo),
        notes=payload.notes,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return _account_out(_account_row(db, user.id, acc.id))


@router.patch("/accounts/{aid}", response_model=AccountOut)
def update_account(aid: int, payload: AccountUpdate, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Actualización parcial. Mandar `saldo` es una CONCILIACIÓN: el saldo
    derivado pasa a ser exactamente el número real que declarás (no se borra
    historia ni se inventan movimientos)."""
    acc = _owned(db, Account, aid, user.id, "la billetera")
    data = payload.model_dump(exclude_none=True)
    if "name" in data:
        nombre = str(data["name"]).strip()
        if not nombre:
            raise HTTPException(400, "El nombre de la billetera no puede estar vacío.")
        if nombre.lower() == DEFAULT_ACCOUNT_NAME.lower():
            raise HTTPException(
                409, f"«{DEFAULT_ACCOUNT_NAME}» ya existe: no se puede usar ese nombre."
            )
        # Case-insensitive como en el alta: si no, podrías tener «Mercado Pago» y
        # «mercado pago» y después el agente no sabría a cuál moverse.
        choque = db.scalar(
            select(Account).where(
                Account.user_id == user.id,
                func.lower(Account.name) == nombre.lower(),
                Account.id != aid,
            )
        )
        if choque:
            raise HTTPException(409, f"Ya tenés una billetera llamada '{nombre}'.")
        acc.name = nombre
    if "kind" in data:
        acc.kind = data["kind"]
    if "notes" in data:
        acc.notes = data["notes"]
    if "saldo" in data:
        analytics.reconcile_account(db, acc, money_to_cents(float(data["saldo"])), user.id)
    else:
        db.commit()
    db.refresh(acc)
    return _account_out(_account_row(db, user.id, aid))


@router.delete("/accounts/{aid}", status_code=204)
def delete_account(
    aid: int,
    reasignar: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Borra la billetera.

    «General» no se puede borrar: es la que recibe todo movimiento sin asignar, y
    sin ella el patrimonio dejaría de contar plata.

    Con movimientos asignado se niega (409): sin `reasignar=1` esos movimientos
    quedarían sin billetera y saldrían del patrimonio. Con `reasignar=1` pasan a
    "General", que también es la billetera por defecto del usuario.
    """
    acc = _owned(db, Account, aid, user.id, "la billetera")
    if acc.name == DEFAULT_ACCOUNT_NAME:
        raise HTTPException(
            409, f"«{DEFAULT_ACCOUNT_NAME}» no se puede borrar: recibe los movimientos sin asignar."
        )
    cuantos = int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user.id, Transaction.cuenta_id == aid
            )
        )
        or 0
    )
    if cuantos and not reasignar:
        raise HTTPException(
            409,
            f"La billetera «{acc.name}» tiene {cuantos} movimiento(s). "
            "Reasignalos o volvé a intentar con reasignar=1 para que pasen a «General».",
        )
    if cuantos:
        general = default_account(db, user.id)
        db.execute(
            update(Transaction)
            .where(Transaction.user_id == user.id, Transaction.cuenta_id == aid)
            .values(cuenta_id=general.id)
        )
    db.delete(acc)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Centro de alertas
# ---------------------------------------------------------------------------

@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [AlertOut(severity=a.severity, kind=a.kind, message=a.message)
            for a in analytics.all_alerts(db, user.id)]


# ---------------------------------------------------------------------------
# Transacciones
# ---------------------------------------------------------------------------

@router.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(payload: TransactionCreate, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    cat = _find_category(db, user.id, payload.category)
    if cat.kind != payload.type:
        raise HTTPException(400, f"La categoría '{cat.name}' es de {cat.kind}, no de {payload.type}")

    goal = None
    if payload.goal and payload.goal.strip():
        goal = db.scalar(
            select(SavingsGoal).where(
                SavingsGoal.user_id == user.id,
                SavingsGoal.name.ilike(payload.goal.strip()),
            )
        )
        if goal is None:
            disponibles = ", ".join(
                g.name
                for g in db.scalars(
                    select(SavingsGoal)
                    .where(SavingsGoal.user_id == user.id)
                    .order_by(SavingsGoal.name)
                ).all()
            )
            raise HTTPException(
                404, f"No existe el objetivo '{payload.goal}'. Disponibles: {disponibles or '(ninguno)'}"
            )

    # La procedencia solo tiene sentido en ingresos: en un gasto el "quién"
    # ya está en la descripción; en un ingreso es el dato que falta.
    source = (payload.source or "").strip() or None
    if payload.type != "income":
        source = None

    # La billetera nunca queda sin resolver: sin elección explícita, el
    # movimiento va a «General» para que el patrimonio no pierda plata.
    cuenta = _find_account(db, user.id, payload.cuenta)

    t = Transaction(
        user_id=user.id,
        type=payload.type,
        amount_cents=money_to_cents(payload.amount),
        category_id=cat.id,
        goal_id=goal.id if goal else None,
        description=payload.description.strip(),
        date=payload.date or date.today(),
        source=source,
        cuenta_id=cuenta.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_out(t)


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    objetivo: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    limite: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        select(Transaction)
        .join(Category)
        .where(Transaction.user_id == user.id, Category.user_id == user.id)
    )
    if tipo:
        q = q.where(Transaction.type == tipo)
    if categoria:
        q = q.where(func.lower(Category.name) == categoria.strip().lower())
    if objetivo:
        goal = db.scalar(
            select(SavingsGoal).where(
                SavingsGoal.user_id == user.id,
                SavingsGoal.name.ilike(objetivo.strip()),
            )
        )
        if goal is None:
            raise HTTPException(404, f"No existe el objetivo '{objetivo}'")
        q = q.where(Transaction.goal_id == goal.id)
    d = _parse_iso(desde)
    if d:
        q = q.where(Transaction.date >= d)
    h = _parse_iso(hasta)
    if h:
        q = q.where(Transaction.date <= h)
    rows = db.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limite)).all()
    return [_to_out(t) for t in rows]


# ---------------------------------------------------------------------------
# Ingresos del mes (vista para cobros por día)
# ---------------------------------------------------------------------------

@router.get("/income", response_model=IncomeMonthOut)
def income_month(mes: Optional[str] = None, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Ingresos del mes: total, subtotal por procedencia y detalle por día."""
    try:
        rows = analytics.income_rows(db, user.id, mes)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    month = analytics.month_bounds(mes)[0].strftime("%Y-%m")
    by_source_map: dict[str, dict] = {}
    by_day_map: dict[str, dict] = {}
    for r in rows:
        b = by_source_map.setdefault(r.source, {"total": 0, "count": 0})
        b["total"] += r.amount_cents
        b["count"] += 1
        d = by_day_map.setdefault(r.date.isoformat(), {"total": 0, "items": []})
        d["total"] += r.amount_cents
        d["items"].append(r)

    by_source = [
        IncomeSourceTotal(
            source=name,
            total=cents_to_money(v["total"]),
            total_cents=v["total"],
            count=v["count"],
        )
        for name, v in sorted(by_source_map.items(), key=lambda kv: -kv[1]["total"])
    ]
    days = [
        IncomeDay(
            date=date.fromisoformat(dia),
            total=cents_to_money(v["total"]),
            total_cents=v["total"],
            items=[
                TransactionOut(
                    id=r.id, type="income", amount=cents_to_money(r.amount_cents),
                    amount_cents=r.amount_cents, category=r.category,
                    description=r.description, date=r.date, goal=None, source=r.source,
                )
                for r in v["items"]
            ],
        )
        for dia, v in sorted(by_day_map.items())
    ]
    total_cents = sum(r.amount_cents for r in rows)
    return IncomeMonthOut(
        month=month,
        total=cents_to_money(total_cents),
        total_cents=total_cents,
        count=len(rows),
        by_source=by_source,
        days=days,
    )


@router.delete("/transactions/{tid}", status_code=204)
def delete_transaction(tid: int, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    t = _owned(db, Transaction, tid, user.id, "la transacción")
    db.delete(t)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=SummaryOut)
def summary(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        select(Transaction)
        .join(Category)
        .where(Transaction.user_id == user.id, Category.user_id == user.id)
    )
    d = _parse_iso(desde)
    if d:
        q = q.where(Transaction.date >= d)
    h = _parse_iso(hasta)
    if h:
        q = q.where(Transaction.date <= h)
    rows = db.scalars(q).all()

    total_income = sum(t.amount_cents for t in rows if t.type == "income")
    total_expense = sum(t.amount_cents for t in rows if t.type == "expense")

    by_category: dict[str, dict] = {}
    for t in rows:
        item = by_category.setdefault(t.category.name, {"kind": t.category.kind, "total_cents": 0})
        item["total_cents"] += t.amount_cents

    period = "personalizado"
    if d and h:
        period = f"{d.isoformat()} → {h.isoformat()}"
    elif d:
        period = f"desde {d.isoformat()}"
    elif h:
        period = f"hasta {h.isoformat()}"
    else:
        period = "todo el historial"

    comp = analytics.comprometido(db, user.id)

    return SummaryOut(
        period=period,
        balance=cents_to_money(total_income - total_expense),
        total_income=cents_to_money(total_income),
        total_expense=cents_to_money(total_expense),
        count=len(rows),
        comprometido=cents_to_money(comp.total_cents),
        comprometido_cents=comp.total_cents,
        comprometido_mes=cents_to_money(comp.mes_cents),
        comprometido_mes_cents=comp.mes_cents,
        vencido=cents_to_money(comp.vencidos_cents),
        vencido_cents=comp.vencidos_cents,
        disponible=cents_to_money(comp.disponible_cents),
        disponible_cents=comp.disponible_cents,
        comprometido_count=comp.count,
        vencido_count=comp.vencidos_count,
        by_category=[
            CategoryTotal(category=name, kind=item["kind"], total=cents_to_money(item["total_cents"]))
            for name, item in sorted(by_category.items(), key=lambda kv: -kv[1]["total_cents"])
        ],
    )


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------

def _run_agent_safe(messages: list[dict], db: Session, pre_confirmed: dict | None = None,
                    user_id: int = 0):
    """Corre el agente traduciendo una falla del proveedor a un 503 entendible.

    El proveedor es un servicio externo: una caída o un 500 suyo no es un error
    de esta app. Sin esto, FastAPI devolvía un 500 con traceback y el chat
    quedaba sin explicación.
    """
    try:
        return run_agent(messages, db, pre_confirmed=pre_confirmed, user_id=user_id)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

@router.post("/agent/chat", response_model=AgentResponse)
def agent_chat(payload: AgentChatRequest, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    return _run_agent_safe(messages, db, user_id=user.id)


@router.post("/agent/confirm", response_model=AgentResponse)
def agent_confirm(payload: AgentConfirmRequest, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    pending = {
        "tool": payload.pending_action.tool,
        "args": payload.pending_action.args,
    }
    return _run_agent_safe(messages, db, pre_confirmed=pending, user_id=user.id)
