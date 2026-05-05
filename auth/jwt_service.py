"""Emissao e verificacao de sdk_jwt RS256.

- Keypair RSA 2048 persistido em disco (gerado no primeiro boot).
- `kid` derivado do fingerprint SHA256 da chave publica, para rotacao suave.
- aud, scope, site_id, jti, exp sao claims obrigatorios.
- Verificacao exige `aud` e rejeita algoritmo diferente de RS256.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


ALGORITHM = "RS256"
PRIVATE_KEY_NAME = "sdk_jwt_private.pem"
PUBLIC_KEY_NAME = "sdk_jwt_public.pem"


@dataclass(frozen=True)
class SdkJwtClaims:
    """Claims extraidos de um sdk_jwt valido."""

    site_id: str
    app_id: str
    ambiente: str
    scope: str
    jti: str
    exp: int
    iat: int


class JwtService:
    """Servico de emissao e verificacao de sdk_jwt RS256."""

    def __init__(self, keys_dir: str, audience: str):
        self._keys_dir = Path(keys_dir)
        self._audience = audience
        self._lock = threading.Lock()
        self._private_pem: Optional[bytes] = None
        self._public_pem: Optional[bytes] = None
        self._kid: Optional[str] = None
        self._garantir_keypair()

    # ---------- gerenciamento de chaves ----------

    def _garantir_keypair(self) -> None:
        """Gera keypair na primeira execucao; carrega do disco nas demais."""
        with self._lock:
            self._keys_dir.mkdir(parents=True, exist_ok=True)
            priv_path = self._keys_dir / PRIVATE_KEY_NAME
            pub_path = self._keys_dir / PUBLIC_KEY_NAME

            if priv_path.exists() and pub_path.exists():
                self._private_pem = priv_path.read_bytes()
                self._public_pem = pub_path.read_bytes()
            else:
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
                    # chmod pode nao existir em Windows com FS nao-NTFS; segue a vida.
                    pass

            self._kid = hashlib.sha256(self._public_pem).hexdigest()[:16]

    @property
    def kid(self) -> str:
        assert self._kid is not None
        return self._kid

    @property
    def audience(self) -> str:
        return self._audience

    def public_pem(self) -> bytes:
        assert self._public_pem is not None
        return self._public_pem

    # ---------- emissao ----------

    def emitir_sdk_jwt(
        self,
        *,
        site_id: str,
        app_id: str,
        ambiente: str,
        ttl_seconds: int,
        scope: str = "ingest",
    ) -> tuple[str, SdkJwtClaims]:
        """Emite um sdk_jwt e retorna (token, claims)."""
        agora = datetime.now(timezone.utc)
        exp = agora + timedelta(seconds=ttl_seconds)
        jti = str(uuid.uuid4())

        payload = {
            "iss": self._audience,
            "aud": self._audience,
            "sub": f"site_{site_id}",
            "site_id": site_id,
            "app_id": app_id,
            "ambiente": ambiente,
            "scope": scope,
            "iat": int(agora.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": jti,
        }
        token = pyjwt.encode(
            payload,
            self._private_pem,
            algorithm=ALGORITHM,
            headers={"kid": self.kid},
        )
        claims = SdkJwtClaims(
            site_id=site_id,
            app_id=app_id,
            ambiente=ambiente,
            scope=scope,
            jti=jti,
            exp=payload["exp"],
            iat=payload["iat"],
        )
        return token, claims

    # ---------- verificacao ----------

    def verificar(self, token: str, *, scope_esperado: str = "ingest") -> SdkJwtClaims:
        """Valida assinatura, aud, exp e scope.

        Levanta pyjwt.PyJWTError (ou subclasses) em caso de falha, e
        `PermissionError` se o scope nao bater.
        """
        decoded = pyjwt.decode(
            token,
            self._public_pem,
            algorithms=[ALGORITHM],
            audience=self._audience,
            options={"require": ["exp", "iat", "aud", "iss", "jti", "site_id", "scope"]},
        )
        if decoded.get("scope") != scope_esperado:
            raise PermissionError(
                f"scope invalido: esperado {scope_esperado}, recebido {decoded.get('scope')}"
            )
        return SdkJwtClaims(
            site_id=decoded["site_id"],
            app_id=decoded.get("app_id", ""),
            ambiente=decoded.get("ambiente", ""),
            scope=decoded["scope"],
            jti=decoded["jti"],
            exp=int(decoded["exp"]),
            iat=int(decoded["iat"]),
        )


# ---------- singleton helpers ----------

_service_instance: Optional[JwtService] = None
_service_lock = threading.Lock()


def obter_servico(
    keys_dir: Optional[str] = None,
    audience: Optional[str] = None,
) -> JwtService:
    """Singleton; primeiro chamador define keys_dir e audience."""
    global _service_instance
    with _service_lock:
        if _service_instance is None:
            if keys_dir is None or audience is None:
                raise RuntimeError(
                    "JwtService nao inicializado; passe keys_dir e audience na primeira chamada"
                )
            _service_instance = JwtService(keys_dir=keys_dir, audience=audience)
        return _service_instance


def resetar_servico() -> None:
    """Apenas para testes."""
    global _service_instance
    with _service_lock:
        _service_instance = None
