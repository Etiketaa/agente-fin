"""Freno de intentos fallidos de login.

Por qué existe: `POST /auth/login` estaba en internet abierto y no tenía ningún
límite. El hash de contraseña (PBKDF2, 200k iteraciones) cuesta ~0.1s por
intento, así que atrasa pero no corta: sin este freno se puede probar
contraseñas indefinidamente desde cualquier lado.

Por qué vive en la base y no en una variable del proceso: en Vercel cada
request puede caer en una instancia distinta, y el proceso no sobrevive entre
requests. Un contador en memoria se perdería en cada llamada, y un atacante lo
reiniciaría sin siquiera darse cuenta.

Por qué la clave es el usuario intentado y no la IP: detrás del proxy de Vercel
todas las conexiones comparten IP de origen, así que limitar por IP dejaría a
todo el mundo cortado junto con un solo atacante. A cambio se acepta que alguien
pueda querer cortar un usuario a propósito: el corte dura lo que dura la ventana
y no borra ningún dato, así que es una molestia y no un daño.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import get_settings
from .models import LoginAttempt

# Un solo mensaje para todos los cortes, exitosos o no. Si el 429 dijera "ese
# usuario no existe" en un caso y "contraseña incorrecta" en otro, un atacante
# mediría a partir de qué intento le cortan y sabría si el usuario existe.
MENSAJE = "Demasiados intentos fallidos. Esperá unos minutos y probá de nuevo."


def clave_de(username: str) -> str:
    """La clave bajo la que se cuentan los intentos.

    Se normaliza igual que el usuario real pero sin validarlo: si la validación
    mandara afuera antes del freno, un nombre mal formado saldría por la rama
    del 401 sin haber pasado por acá, y ahí no habría límite.
    """
    return (username or "").strip().lower()[:80]


def _ventana() -> timedelta:
    return timedelta(minutes=get_settings().login_window_minutes)


def verificar(db: Session, clave: str) -> None:
    """Levanta 429 si esta clave está al tope; no devuelve nada si pasa.

    Se llama ANTES de mirar la contraseña. Si se llamara después, el atacante ya
    habría probado su intento con ese mismo request y el freno no frenaría nada.

    Sólo lee: ninguna escritura en el camino exitoso. Una clave con la ventana
    vencida no bloquea, aunque su fila todavía esté en la base.
    """
    fila = db.get(LoginAttempt, clave)
    if fila is None:
        return
    ahora = datetime.now()
    if ahora - fila.ultima_prueba > _ventana():
        return  # vencida: no bloquea. La fila la barre quien la reescribe.
    if fila.intentos < get_settings().login_max_attempts:
        return
    restante = (fila.ultima_prueba + _ventana() - ahora).total_seconds()
    raise HTTPException(
        429,
        MENSAJE,
        headers={"Retry-After": str(max(1, int(restante)))},
    )


def registrar_fallo(db: Session, clave: str) -> None:
    """Suma un intento fallido a la clave. Va DESPUÉS del rechazo, una sola vez
    por request: si dos ramas distintas lo llamaban, un mismo error contaría
    doble y cortaría antes de tiempo.

    Barre de paso las claves vencidas. Hace falta acá y no en `verificar`,
    porque es donde nacen filas nuevas: alguien que prueba usuarios inventados
    genera una fila por cada uno, y sin este barrido la tabla crecería sin límite.
    """
    ahora = datetime.now()
    db.execute(delete(LoginAttempt).where(LoginAttempt.ultima_prueba < ahora - _ventana()))
    db.commit()  # así el get de abajo lee lo que quedó, no lo que se acabó de borrar

    fila = db.get(LoginAttempt, clave)
    if fila is None:
        db.add(LoginAttempt(clave=clave, intentos=1, ultima_prueba=ahora))
    else:
        fila.intentos += 1
        fila.ultima_prueba = ahora
    db.commit()


def limpiar(db: Session, clave: str) -> None:
    """Borra la racha cuando el login salió bien.

    Lo que se quiere cortar es el adivinado: quien ya sabe la clave no necesita
    freno, y dejarle la racha puesta sería cortarlo a él por culpa de alguien
    que falló antes.
    """
    db.execute(delete(LoginAttempt).where(LoginAttempt.clave == clave))
    db.commit()
