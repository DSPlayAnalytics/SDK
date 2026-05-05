"""Middleware de autenticacao para rotas HTTP e handshake Socket.IO.

Expoe:
- `require_scope(scope)` — decorator Flask que exige Authorization: Bearer <sdk_jwt>
  com `scope` e `aud` corretos. Rejeita com 401/403 antes do handler.
- `validar_token_socketio(token, scope_esperado)` — helper para ser chamado
  dentro do handler `connect` do Socket.IO; levanta excecao com codigo claro.
- `normalizar_origin(origin)` — normaliza scheme+host (remove porta default e path).

Toda falha gera log com o motivo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional
from urllib.parse import urlparse

import jwt as pyjwt
from flask import g, jsonify, request

from .jwt_service import JwtService, SdkJwtClaims, obter_servico


logger = logging.getLogger("auth")


class AuthError(Exception):
    """Erro de autenticacao com codigo e status HTTP amigaveis."""

    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------- helpers ----------

_PORTAS_DEFAULT = {"http": 80, "https": 443}


def normalizar_origin(origin: Optional[str]) -> Optional[str]:
    """Converte header Origin em "scheme://host" estavel.

    Remove porta default, path, query e trailing slash. `None` -> `None`.
    """
    if not origin:
        return None
    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.hostname:
        return None
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    porta = parsed.port
    if porta and porta != _PORTAS_DEFAULT.get(scheme):
        return f"{scheme}://{host}:{porta}"
    return f"{scheme}://{host}"


def _extrair_bearer() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip() or None


# ---------- validacao central ----------

@dataclass(frozen=True)
class AuthContext:
    claims: SdkJwtClaims
    origin: Optional[str]


def _validar(token: str, scope_esperado: str, servico: JwtService) -> SdkJwtClaims:
    try:
        return servico.verificar(token, scope_esperado=scope_esperado)
    except pyjwt.ExpiredSignatureError:
        raise AuthError("TOKEN_EXPIRED", "Token expirado", status=401)
    except pyjwt.InvalidAudienceError:
        raise AuthError("INVALID_AUDIENCE", "Audience invalido", status=401)
    except pyjwt.InvalidSignatureError:
        raise AuthError("INVALID_SIGNATURE", "Assinatura invalida", status=401)
    except pyjwt.MissingRequiredClaimError as exc:
        raise AuthError("MISSING_CLAIM", f"Claim obrigatorio ausente: {exc.claim}", status=401)
    except pyjwt.InvalidTokenError as exc:
        raise AuthError("INVALID_TOKEN", f"Token invalido: {exc}", status=401)
    except PermissionError as exc:
        raise AuthError("INVALID_SCOPE", str(exc), status=403)


# ---------- decorator HTTP ----------

def require_scope(scope_esperado: str) -> Callable:
    """Decorator para rotas Flask que exigem sdk_jwt valido com `scope`.

    Em caso de falha, retorna JSON com `code` e `message` e status 401/403.
    Em sucesso, injeta `g.auth: AuthContext` para o handler.
    """

    def decorator(handler: Callable) -> Callable:
        @wraps(handler)
        def wrapper(*args, **kwargs):
            token = _extrair_bearer()
            if not token:
                logger.info("auth=falha motivo=token_ausente path=%s", request.path)
                return jsonify({"status": "error", "code": "TOKEN_MISSING",
                                "message": "Authorization Bearer ausente"}), 401
            try:
                servico = obter_servico()
                claims = _validar(token, scope_esperado, servico)
            except AuthError as err:
                logger.info("auth=falha code=%s path=%s", err.code, request.path)
                return jsonify({"status": "error", "code": err.code,
                                "message": err.message}), err.status

            origin = normalizar_origin(request.headers.get("Origin"))
            g.auth = AuthContext(claims=claims, origin=origin)
            return handler(*args, **kwargs)

        return wrapper

    return decorator


# ---------- handshake Socket.IO ----------

def validar_token_socketio(token: str, scope_esperado: str = "ingest") -> SdkJwtClaims:
    """Valida sdk_jwt vindo do handshake Socket.IO.

    Retorna claims em caso de sucesso. Levanta AuthError em caso de falha
    — o chamador decide se desconecta ou emite evento de erro.
    """
    if not token:
        raise AuthError("TOKEN_MISSING", "Token ausente no handshake", status=401)
    servico = obter_servico()
    return _validar(token, scope_esperado, servico)
