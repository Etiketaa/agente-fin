"""Autenticación: hashing de contraseñas y sesiones por token.

Sin dependencias nuevas: PBKDF2-SHA256 de la stdlib para contraseñas y
`secrets` para tokens opacos. En la base solo se guardan hashes, nunca el
token en claro ni la contraseña.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

# Iteraciones de PBKDF2: costo deliberado (~0.1s por login en esta máquina).
# Suficiente para frenar fuerza bruta sin molestar al usuario real.
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Contraseña → 'pbkdf2-sha256$iteraciones$salt$hash' (todo hex)."""
    if len(password.encode()) < 1:
        raise ValueError("La contraseña no puede estar vacía.")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2-sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Compara en tiempo constante para no filtrar por timing."""
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2-sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    """Token opaco de sesión (32 bytes de entropía, URL-safe)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 del token: lo que se guarda y se busca en la base."""
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry(days: int) -> datetime:
    """Momento en que deja de valer una sesión emitida ahora.

    Un token es un secreto de 256 bits que viaja en un header, y en un celular
    compartido o en el navegador de otra persona puede quedar expuesto. Por eso la
    sesión tiene fecha de muerte propia y no depende de que su dueño se acuerde de
    hacer logout: el token deja de abrir la puerta solo, sin borrar ningún dato.
    """
    return datetime.now() + timedelta(days=days)


def valid_username(username: str) -> str:
    """Normaliza y valida un nombre de usuario. Devuelve el normalizado."""
    name = username.strip().lower()
    if not (3 <= len(name) <= 40):
        raise ValueError("El usuario debe tener entre 3 y 40 caracteres.")
    if not all(c.isalnum() or c in ("_", "-", ".") for c in name):
        raise ValueError("El usuario solo puede tener letras, números, _ - .")
    return name


def valid_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
