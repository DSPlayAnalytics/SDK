"""Email diário com resumo de consumo de quota por site.

Envia um email para cada cliente que ontem usou >= 80% da quota diária,
informando o percentual consumido e o plano. Sites acima de 100% (quota
atingida, eventos rejeitados) recebem mensagem de alerta mais urgente.

Entrypoint de cron (container backend, via APScheduler ou cron systemd):
    python -m scripts.email_diario

Ou direto como script:
    python backend/scripts/email_diario.py

Envs requeridos (mesmo .env do backend):
    TENANTS_DATABASE_URL   — postgres://... ou sqlite:///...
    USERS_DATABASE_PATH    — caminho do SQLite de clientes_users (se diferente do tenants)
    RESEND_API_KEY         — ausente → fallback stdout (dev)
    EMAIL_FROM             — remetente (default: no-reply@dsplayground.com.br)
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

logger = logging.getLogger(__name__)

THRESHOLD_AVISO: float = 0.80
THRESHOLD_LIMITE: float = 1.00


# ─── contrato de dependência ────────────────────────────────────────────────

class _TenantsSource(Protocol):
    def listar_sites(self): ...
    def obter_quota(self, site_id: str): ...
    def consumo_em_dia(self, site_id: str, dia: date) -> int: ...


class _UsersSource(Protocol):
    def obter_user_por_site(self, site_id: str): ...


# ─── resultado ────────────────────────────────────────────────────────────────

@dataclass
class ResumoEmailDiario:
    enviados: int = 0
    pulados: int = 0
    sem_email: int = 0
    falhas: int = 0
    detalhes: list = field(default_factory=list)


# ─── lógica pura ─────────────────────────────────────────────────────────────

def _formatar_corpo(slug: str, consumo: int, limite: int, pct: float, data: date) -> str:
    pct_str = f"{pct * 100:.0f}%"
    data_str = data.strftime("%d/%m/%Y")

    if pct >= THRESHOLD_LIMITE:
        nivel = "⚠️  Limite diário atingido"
        detalhe = (
            f"Seu site atingiu {pct_str} da quota diária em {data_str}. "
            f"Eventos acima do limite são descartados automaticamente. "
            f"Considere fazer upgrade do plano para aumentar sua quota."
        )
    else:
        nivel = "📊 Aviso de uso"
        detalhe = (
            f"Seu site usou {pct_str} da quota diária em {data_str}. "
            f"Se o consumo continuar crescendo, eventos podem começar a ser descartados."
        )

    return (
        f"{nivel} — {slug}\n\n"
        f"{detalhe}\n\n"
        f"Eventos ontem: {consumo:,} / {limite:,} ({pct_str})\n\n"
        f"Veja seus dados em https://app.dsplayground.com.br/cliente/metricas\n"
        f"Configurações: https://dsplayground.com.br/cliente/configuracoes\n\n"
        f"—\n"
        f"dsplayground.com.br — Responda para cancelar notificações."
    )


def _formatar_assunto(slug: str, pct: float) -> str:
    pct_str = f"{pct * 100:.0f}%"
    if pct >= THRESHOLD_LIMITE:
        return f"[dsplayground] Limite diário atingido — {slug}"
    return f"[dsplayground] {pct_str} da quota usada ontem — {slug}"


def executar_rodada_diaria(
    tenants_repo: _TenantsSource,
    users_repo: _UsersSource,
    sender,
    data_referencia: date,
) -> ResumoEmailDiario:
    """Itera todos os sites e envia email para os que ultrapassaram o threshold."""
    resumo = ResumoEmailDiario()

    for site in tenants_repo.listar_sites():
        if site.status != "ativo":
            resumo.pulados += 1
            logger.info("evento=email_diario_skip motivo=inativo site_id=%s", site.id)
            continue

        quota = tenants_repo.obter_quota(site.id)
        if quota is None or quota.eventos_por_dia <= 0:
            resumo.pulados += 1
            logger.info("evento=email_diario_skip motivo=sem_quota site_id=%s", site.id)
            continue

        consumo = tenants_repo.consumo_em_dia(site.id, data_referencia)
        pct = consumo / quota.eventos_por_dia

        if pct < THRESHOLD_AVISO:
            resumo.pulados += 1
            continue

        user = users_repo.obter_user_por_site(site.id)
        if user is None:
            resumo.sem_email += 1
            logger.warning("evento=email_diario_sem_user site_id=%s", site.id)
            continue

        corpo = _formatar_corpo(site.slug, consumo, quota.eventos_por_dia, pct, data_referencia)
        assunto = _formatar_assunto(site.slug, pct)

        try:
            ok = sender.enviar(destinatario=user.email, assunto=assunto, corpo_texto=corpo)
        except Exception as exc:
            resumo.falhas += 1
            resumo.detalhes.append(f"{site.slug}: {exc!r}")
            logger.warning("evento=email_diario_falha site_id=%s erro=%r", site.id, exc)
            continue

        if ok:
            resumo.enviados += 1
            logger.info("evento=email_diario_ok site_id=%s email=%s pct=%.0f",
                        site.id, user.email, pct * 100)
        else:
            resumo.falhas += 1
            logger.warning("evento=email_diario_falha_envio site_id=%s", site.id)

    logger.info(
        "evento=email_diario_rodada_concluida enviados=%d pulados=%d "
        "sem_email=%d falhas=%d",
        resumo.enviados, resumo.pulados, resumo.sem_email, resumo.falhas,
    )
    return resumo


# ─── adapters para produção ───────────────────────────────────────────────────

class _TenantsAdapter:
    """Wraps TenantsRepo delegando ao protocolo base."""

    def __init__(self, repo):
        self._repo = repo

    def listar_sites(self):
        return self._repo.listar_sites()

    def obter_quota(self, site_id):
        return self._repo.obter_quota(site_id)

    def consumo_em_dia(self, site_id: str, dia: date) -> int:
        return self._repo.consumo_em_dia(site_id, dia)


class _UsersAdapter:
    """Wraps ClientesUsersRepo delegando ao protocolo base."""

    def __init__(self, repo):
        self._repo = repo

    def obter_user_por_site(self, site_id: str):
        return self._repo.obter_user_por_site(site_id)


# ─── entrypoint ───────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from auth.tenants_repo import criar_tenants_repo
    from auth.clientes_users_repo import criar_repo_padrao
    from auth.email_sender import criar_sender_padrao

    db_url = os.environ.get("TENANTS_DATABASE_URL", "")
    if not db_url:
        logger.error("evento=email_diario_erro motivo=TENANTS_DATABASE_URL ausente")
        return 1

    tenants_raw = criar_tenants_repo(db_url)
    users_raw = criar_repo_padrao()

    tenants = _TenantsAdapter(tenants_raw)
    users = _UsersAdapter(users_raw)
    sender = criar_sender_padrao()

    ontem = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    resumo = executar_rodada_diaria(tenants, users, sender, ontem)

    return 0 if resumo.falhas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
