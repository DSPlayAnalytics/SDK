"""Camada de servico de sessao e magic-link para o dashboard do cliente.

Encapsula a politica de negocio em cima de `ClientesUsersRepo`:
  - geracao de token plaintext 32B + armazenamento so do hash sha256
  - validacao de cookie (expirou? revogado? existe?)
  - rate-limit de emissao de magic-link (por user e por IP)
  - hashing de senha via werkzeug.security (pbkdf2:sha256)

Nao toca Flask. Recebe ClientesUsersRepo + instanciar com parametros de TTL
e limites de rate-limit, permite customizar em testes.

Referencia: ark/docs/dashboard-cliente.md (secoes 7, 8, 9).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pyotp
from werkzeug.security import check_password_hash, generate_password_hash

from .clientes_users_repo import (
    ClienteUser,
    ClientesUsersRepo,
    MagicLink,
    Sessao,
    hash_token,
)


TOKEN_BYTES = 32  # 256-bit — secrets.token_urlsafe(32) -> ~43 chars


@dataclass(frozen=True)
class SessaoCriada:
    cookie_plaintext: str
    sessao: Sessao


@dataclass(frozen=True)
class MagicLinkCriado:
    token_plaintext: str
    magic_link: MagicLink


class RateLimitExcedido(Exception):
    """Cliente pediu magic-links demais num curto intervalo."""


class SessaoService:
    def __init__(
        self,
        repo: ClientesUsersRepo,
        *,
        sessao_ttl_segundos: int = 7 * 24 * 3600,        # 7 dias
        magic_link_ttl_segundos: int = 15 * 60,          # 15 min
        max_magic_links_por_user: int = 3,
        max_magic_links_por_ip: int = 10,
        janela_rate_limit_segundos: int = 15 * 60,       # 15 min
    ):
        self._repo = repo
        self._sessao_ttl = sessao_ttl_segundos
        self._magic_ttl = magic_link_ttl_segundos
        self._max_magic_user = max_magic_links_por_user
        self._max_magic_ip = max_magic_links_por_ip
        self._janela = janela_rate_limit_segundos

    # ---------- users ----------

    def criar_user(self, site_id: str, email: str, *, papel: str = "viewer",
                   senha: Optional[str] = None) -> ClienteUser:
        senha_hash = generate_password_hash(senha) if senha else None
        return self._repo.criar_user(site_id, email, papel=papel, senha_hash=senha_hash)

    def autenticar_por_senha(self, email: str, senha: str) -> Optional[ClienteUser]:
        user = self._repo.obter_user_por_email(email)
        if user is None or not user.ativo or user.senha_hash is None:
            return None
        if not check_password_hash(user.senha_hash, senha):
            return None
        self._repo.registrar_login(user.id)
        return user

    # ---------- alterar credenciais ----------

    _SENHA_MIN = 8
    _RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    def alterar_senha(self, user_id: str, senha_atual: str, nova_senha: str) -> bool:
        """Verifica senha atual e atualiza pra nova. Retorna True se OK."""
        user = self._repo.obter_user(user_id)
        if user is None or user.senha_hash is None:
            return False
        if not check_password_hash(user.senha_hash, senha_atual):
            return False
        if not nova_senha or len(nova_senha) < self._SENHA_MIN:
            return False
        novo_hash = generate_password_hash(nova_senha)
        self._repo.atualizar_senha_hash(user_id, novo_hash)
        return True

    def alterar_email(self, user_id: str, senha_atual: str, novo_email: str) -> Optional[str]:
        """Verifica senha + atualiza email. Retorna None se OK ou codigo de erro.

        Codigos: SENHA_INVALIDA, EMAIL_INVALIDO, EMAIL_JA_CADASTRADO.
        """
        user = self._repo.obter_user(user_id)
        if user is None or user.senha_hash is None:
            return "SENHA_INVALIDA"
        if not check_password_hash(user.senha_hash, senha_atual):
            return "SENHA_INVALIDA"
        if not novo_email or not self._RE_EMAIL.match(novo_email):
            return "EMAIL_INVALIDO"
        existente = self._repo.obter_user_por_email(novo_email)
        if existente is not None and existente.id != user_id:
            return "EMAIL_JA_CADASTRADO"
        try:
            self._repo.atualizar_email(user_id, novo_email)
        except Exception:
            # IntegrityError em corrida de unique — trata como ja cadastrado.
            return "EMAIL_JA_CADASTRADO"
        return None

    # ---------- sessoes ----------

    def criar_sessao(self, user_id: str, *, ip: Optional[str] = None,
                     user_agent: Optional[str] = None) -> SessaoCriada:
        cookie_plaintext = secrets.token_urlsafe(TOKEN_BYTES)
        token_hash_ = hash_token(cookie_plaintext)
        expira_em = datetime.now(timezone.utc) + timedelta(seconds=self._sessao_ttl)
        sessao = self._repo.criar_sessao(
            user_id, token_hash_, expira_em=expira_em, ip=ip, user_agent=user_agent,
        )
        return SessaoCriada(cookie_plaintext=cookie_plaintext, sessao=sessao)

    def validar_cookie(self, cookie_plaintext: str) -> Optional[ClienteUser]:
        """Valida cookie e retorna o user correspondente; None se invalido/expirado/revogado/user inativo."""
        if not cookie_plaintext:
            return None
        sessao = self._repo.obter_sessao_por_hash(hash_token(cookie_plaintext))
        if sessao is None:
            return None
        if sessao.revogada_em is not None:
            return None
        agora = datetime.now(timezone.utc)
        expira = sessao.expira_em
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        if expira <= agora:
            return None
        user = self._repo.obter_user(sessao.user_id)
        if user is None or not user.ativo:
            return None
        return user

    def revogar_sessao(self, cookie_plaintext: str) -> None:
        self._repo.revogar_sessao(hash_token(cookie_plaintext))

    # ---------- magic-links ----------

    def solicitar_magic_link(
        self, email: str, *, ip: Optional[str] = None, tipo: str = "login",
    ) -> Optional[MagicLinkCriado]:
        """Gera magic-link se o email existir e rate-limit permitir.

        `tipo`:
          - 'login' (default, legado): magic-link entra direto no dashboard.
          - 'reset': magic-link redireciona pra form de nova senha.
                     Sessao so e criada apos POST /confirmar com nova_senha.

        Retorna `None` se o email nao existe (para nao vazar existencia — o
        endpoint sempre responde 200). Se rate-limit estourar, levanta
        `RateLimitExcedido` — o endpoint deve traduzir em 200 ok mas nao
        enviar email (ou retornar 429 dependendo da politica).
        """
        user = self._repo.obter_user_por_email(email)
        if user is None or not user.ativo:
            return None

        # rate-limit por user (compartilhado entre tipos: brute force pra
        # 'reset' tambem cega rate-limit de 'login' e vice-versa)
        qtd_user = self._repo.contar_magic_links_recentes(user.id, self._janela)
        if qtd_user >= self._max_magic_user:
            raise RateLimitExcedido(f"max_por_user={self._max_magic_user}")

        # rate-limit por IP (apenas se IP conhecido)
        if ip:
            qtd_ip = self._repo.contar_magic_links_por_ip(ip, self._janela)
            if qtd_ip >= self._max_magic_ip:
                raise RateLimitExcedido(f"max_por_ip={self._max_magic_ip}")

        token_plaintext = secrets.token_urlsafe(TOKEN_BYTES)
        token_hash_ = hash_token(token_plaintext)
        expira_em = datetime.now(timezone.utc) + timedelta(seconds=self._magic_ttl)
        magic = self._repo.criar_magic_link(
            user.id, token_hash_, expira_em=expira_em, ip=ip, tipo=tipo,
        )
        return MagicLinkCriado(token_plaintext=token_plaintext, magic_link=magic)

    def consumir_magic_link(
        self, token_plaintext: str, *, ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[SessaoCriada]:
        """Consome magic-link de tipo='login' e cria sessao.

        `None` se token invalido/expirado/ja consumido OU se tipo!='login'
        (recuperacao de senha precisa usar consumir_magic_link_reset +
        password change explicito antes de criar sessao).
        """
        magic = self._validar_magic_link_disponivel(token_plaintext)
        if magic is None or magic.tipo != "login":
            return None

        # atomico: so prossegue se consumir realmente marcou o link
        if not self._repo.consumir_magic_link(hash_token(token_plaintext)):
            return None

        self._repo.registrar_login(magic.user_id)
        return self.criar_sessao(magic.user_id, ip=ip, user_agent=user_agent)

    def validar_magic_link_reset(self, token_plaintext: str) -> Optional[MagicLink]:
        """Valida (sem consumir) um magic-link de tipo='reset'.

        Usado pelo endpoint GET /recuperar-senha/verificar pra checar se o
        token e valido antes de mostrar o form de nova senha. NAO consome
        — consumir so acontece no POST /recuperar-senha/confirmar com a
        nova senha definida.

        Retorna o MagicLink se valido + tipo='reset', else None.
        """
        magic = self._validar_magic_link_disponivel(token_plaintext)
        if magic is None or magic.tipo != "reset":
            return None
        return magic

    def consumir_magic_link_reset(
        self, token_plaintext: str, nova_senha: str, *,
        ip: Optional[str] = None, user_agent: Optional[str] = None,
    ) -> Optional[SessaoCriada]:
        """Consome magic-link de tipo='reset', troca senha, cria sessao.

        Retorna `None` se token invalido/expirado/ja consumido/tipo errado
        OU se nova_senha for muito curta. Atomico no sentido pratico: token
        e marcado consumido ANTES da troca de senha — se a troca falhar,
        token nao serve mais (operador pede novo). Trade-off por simplicidade.

        O token e a prova de identidade (so quem tem o link no email
        chegou aqui), entao NAO exige senha atual — esse e o ponto do
        fluxo de "esqueci minha senha".
        """
        if not nova_senha or len(nova_senha) < self._SENHA_MIN:
            return None

        magic = self._validar_magic_link_disponivel(token_plaintext)
        if magic is None or magic.tipo != "reset":
            return None

        if not self._repo.consumir_magic_link(hash_token(token_plaintext)):
            return None

        novo_hash = generate_password_hash(nova_senha)
        self._repo.atualizar_senha_hash(magic.user_id, novo_hash)
        self._repo.registrar_login(magic.user_id)
        return self.criar_sessao(magic.user_id, ip=ip, user_agent=user_agent)

    # ---------- totp ----------

    def iniciar_configuracao_totp(self, user_id: str) -> tuple[str, str]:
        """Gera secret TOTP (nao salva ainda). Retorna (secret, otpauth_uri).
        Cliente exibe QR code e chama confirmar_totp_setup com o mesmo secret.
        """
        user = self._repo.obter_user(user_id)
        if user is None:
            raise ValueError("user nao encontrado")
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=user.email, issuer_name="DSPlay Analytics"
        )
        return secret, uri

    def confirmar_totp_setup(self, user_id: str, secret: str, codigo: str) -> bool:
        """Verifica o codigo contra o secret pendente e salva se valido."""
        if not pyotp.TOTP(secret).verify(codigo, valid_window=1):
            return False
        self._repo.habilitar_totp(user_id, secret)
        return True

    def verificar_totp(self, user_id: str, codigo: str) -> bool:
        """Verifica codigo TOTP. Rejeita replay do mesmo OTP dentro da janela de validade."""
        secret = self._repo.obter_totp_secret(user_id)
        if not secret:
            return False
        if not pyotp.TOTP(secret).verify(codigo, valid_window=1):
            return False
        if self._repo.obter_ultimo_otp_usado(user_id) == codigo:
            return False
        self._repo.registrar_otp_usado(user_id, codigo)
        return True

    def completar_login_totp(
        self, user_id: str, codigo: str, *, ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional["SessaoCriada"]:
        """Verifica TOTP e cria sessao se valido. None se codigo errado."""
        if not self.verificar_totp(user_id, codigo):
            return None
        self._repo.registrar_login(user_id)
        return self.criar_sessao(user_id, ip=ip, user_agent=user_agent)

    def desabilitar_totp(self, user_id: str, codigo_ou_senha: str) -> Optional[str]:
        """Desabilita TOTP. Aceita codigo TOTP valido OU senha atual.
        Retorna None se OK ou codigo de erro: TOTP_NAO_HABILITADO, CREDENCIAL_INVALIDA.
        """
        user = self._repo.obter_user(user_id)
        if user is None:
            return "CREDENCIAL_INVALIDA"
        if not user.totp_habilitado:
            return "TOTP_NAO_HABILITADO"
        secret = self._repo.obter_totp_secret(user_id)
        ok_totp = bool(secret and pyotp.TOTP(secret).verify(codigo_ou_senha, valid_window=1))
        ok_senha = bool(
            user.senha_hash and check_password_hash(user.senha_hash, codigo_ou_senha)
        )
        if not (ok_totp or ok_senha):
            return "CREDENCIAL_INVALIDA"
        self._repo.desabilitar_totp(user_id)
        return None

    # ---------- helpers ----------
    def _validar_magic_link_disponivel(self, token_plaintext: str):
        """Carrega o magic-link e retorna se ainda valido (nao consumido,
        nao expirado). NAO marca como consumido."""
        if not token_plaintext:
            return None
        token_hash_ = hash_token(token_plaintext)
        magic = self._repo.obter_magic_link_por_hash(token_hash_)
        if magic is None or magic.consumido_em is not None:
            return None
        expira = magic.expira_em
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        if expira <= datetime.now(timezone.utc):
            return None
        return magic


# Exposto para teste / utilidades administrativas
__all__ = [
    "SessaoService",
    "SessaoCriada",
    "MagicLinkCriado",
    "RateLimitExcedido",
    "TOKEN_BYTES",
]
