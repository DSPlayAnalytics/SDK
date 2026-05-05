"""Emissao e verificacao de embed_jwt RS256.

Gera tokens curtos (TTL 60-600s) assinados com a mesma chave RSA do `sdk_jwt`
(volume `portifolio_backend_keys`, arquivos `sdk_jwt_{private,public}.pem`).
Audience separada (`embed.dsplayground.com.br`) garante que token de embed
nao serve pra autenticar SDK e vice-versa.

Claims:
  iss=dsplayground.com.br, aud=embed.dsplayground.com.br, scope=embed:read,
  site_id, grafico_id, user_id, iat, exp, jti.

Revogacao: cada token tem `jti` (UUID4); tabela `embed_jwt_revogados` no Postgres
permite invalidar antes do exp (compliance, banimento, leak detectado). Verificacao
em /embed/dados consulta a tabela e rejeita 401 se jti revogado. TTL curto continua
sendo a primeira linha de defesa — revogacao e uma rede de seguranca.

Referencia: ark/docs/embed-iframe.md (Fase 1 — contratos tecnicos).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt as pyjwt


ALGORITHM = "RS256"
EMBED_AUDIENCE = "embed.dsplayground.com.br"
EMBED_ISSUER = "dsplayground.com.br"
EMBED_SCOPE = "embed:read"

PRIVATE_KEY_NAME = "sdk_jwt_private.pem"
PUBLIC_KEY_NAME = "sdk_jwt_public.pem"

TTL_MIN = 60
TTL_MAX = 600
TTL_DEFAULT = 300


@dataclass(frozen=True)
class EmbedClaims:
    site_id: str
    grafico_id: str
    user_id: str
    scope: str
    iat: int
    exp: int
    jti: str


class EmbedJwtService:
    """Servico de emissao e verificacao de embed_jwt RS256."""

    def __init__(self, keys_dir: str):
        self._keys_dir = Path(keys_dir)
        self._lock = threading.Lock()
        self._private_pem: Optional[bytes] = None
        self._public_pem: Optional[bytes] = None
        self._garantir_keypair()

    def _garantir_keypair(self) -> None:
        """Carrega keypair existente; gera novo se ausente.

        Compartilha keypair com `JwtService` (mesmo arquivo no disco) — a
        primeira instancia que rodar gera as chaves, as demais leem do disco.
        """
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        with self._lock:
            self._keys_dir.mkdir(parents=True, exist_ok=True)
            priv_path = self._keys_dir / PRIVATE_KEY_NAME
            pub_path = self._keys_dir / PUBLIC_KEY_NAME

            if priv_path.exists() and pub_path.exists():
                self._private_pem = priv_path.read_bytes()
                self._public_pem = pub_path.read_bytes()
                return

            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self._private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            self._public_pem = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            priv_path.write_bytes(self._private_pem)
            pub_path.write_bytes(self._public_pem)
            try:
                priv_path.chmod(0o600)
            except (OSError, NotImplementedError):
                pass

    def public_pem(self) -> bytes:
        assert self._public_pem is not None
        return self._public_pem

    def emitir(
        self,
        *,
        site_id: str,
        grafico_id: str,
        user_id: str,
        ttl_segundos: int = TTL_DEFAULT,
    ) -> tuple[str, EmbedClaims]:
        """Emite token e retorna (token_jwt, claims). TTL clampeado em [60, 600]."""
        ttl = max(TTL_MIN, min(TTL_MAX, ttl_segundos))
        agora = datetime.now(timezone.utc)
        exp = agora + timedelta(seconds=ttl)
        jti = uuid.uuid4().hex
        payload = {
            "iss": EMBED_ISSUER,
            "aud": EMBED_AUDIENCE,
            "sub": f"embed:{site_id}:{grafico_id}",
            "scope": EMBED_SCOPE,
            "site_id": site_id,
            "grafico_id": grafico_id,
            "user_id": user_id,
            "iat": int(agora.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": jti,
        }
        token = pyjwt.encode(payload, self._private_pem, algorithm=ALGORITHM)
        claims = EmbedClaims(
            site_id=site_id, grafico_id=grafico_id, user_id=user_id,
            scope=EMBED_SCOPE, iat=payload["iat"], exp=payload["exp"], jti=jti,
        )
        return token, claims

    def verificar(self, token: str) -> EmbedClaims:
        """Valida assinatura, aud, exp e scope. Levanta pyjwt.PyJWTError em falha.

        Nao consulta tabela de revogacao — caller (rota /embed/dados) faz isso
        apos a verificacao de assinatura para manter este servico desacoplado
        do TenantsRepo (testavel sem DB).
        """
        decoded = pyjwt.decode(
            token,
            self._public_pem,
            algorithms=[ALGORITHM],
            audience=EMBED_AUDIENCE,
            options={"require": ["exp", "iat", "aud", "iss", "scope",
                                 "site_id", "grafico_id", "user_id", "jti"]},
        )
        if decoded.get("scope") != EMBED_SCOPE:
            raise pyjwt.InvalidTokenError(
                f"scope invalido: esperado {EMBED_SCOPE}"
            )
        return EmbedClaims(
            site_id=decoded["site_id"],
            grafico_id=decoded["grafico_id"],
            user_id=decoded["user_id"],
            scope=decoded["scope"],
            iat=int(decoded["iat"]),
            exp=int(decoded["exp"]),
            jti=decoded["jti"],
        )
