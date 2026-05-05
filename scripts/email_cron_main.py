"""Entrypoint do container `email-cron` (profile opt-in).

APScheduler com cron diário 07:00 UTC chamando `executar_rodada_diaria`.
Configuração via env vars (12-factor):

  TENANTS_DATABASE_URL   — postgres://... (Postgres em prod)
  RESEND_API_KEY         — ausente → fallback stdout (dev/CI)
  EMAIL_FROM             — remetente (default: no-reply@dsplayground.com.br)
  EMAIL_CRON_HORA        — hora UTC do cron (default: 7)
  EMAIL_CRON_MINUTO      — minuto do cron (default: 0)
  EMAIL_RUN_ON_START     — 'true' → executa imediatamente ao boot (backfill/debug)

Logs estruturados (`evento=email_diario_*`) — mesmo padrão do backend principal.
"""
import logging
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.tenants_repo import criar_tenants_repo
from auth.email_sender import criar_sender_padrao
from scripts.email_diario import executar_rodada_diaria, _TenantsAdapter, _UsersAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s evento_loglevel=%(levelname)s %(message)s",
)
logger = logging.getLogger("email_cron.main")


def _env_obrigatoria(nome: str) -> str:
    valor = os.environ.get(nome, "").strip()
    if not valor:
        logger.error("evento=email_cron_boot_falhou motivo=env_ausente var=%s", nome)
        sys.exit(1)
    return valor


def _construir_dependencias():
    db_url = _env_obrigatoria("TENANTS_DATABASE_URL")
    tenants_raw = criar_tenants_repo(db_url)

    from auth.clientes_users_repo import criar_clientes_users_repo
    users_raw = criar_clientes_users_repo(db_url)

    tenants = _TenantsAdapter(tenants_raw)
    users = _UsersAdapter(users_raw)
    sender = criar_sender_padrao()
    return tenants, users, sender


def _rodar_uma_vez(tenants, users, sender) -> None:
    ontem = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    logger.info("evento=email_cron_rodada_iniciada data_ref=%s", ontem)
    resumo = executar_rodada_diaria(tenants, users, sender, ontem)
    logger.info(
        "evento=email_cron_rodada_concluida enviados=%d pulados=%d sem_email=%d falhas=%d",
        resumo.enviados, resumo.pulados, resumo.sem_email, resumo.falhas,
    )


def main() -> None:
    tenants, users, sender = _construir_dependencias()

    if os.environ.get("EMAIL_RUN_ON_START", "false").lower() == "true":
        logger.info("evento=email_cron_run_on_start")
        _rodar_uma_vez(tenants, users, sender)

    hora = int(os.environ.get("EMAIL_CRON_HORA", "7"))
    minuto = int(os.environ.get("EMAIL_CRON_MINUTO", "0"))

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: _rodar_uma_vez(tenants, users, sender),
        trigger="cron",
        hour=hora,
        minute=minuto,
        id="email_diario",
    )

    def _shutdown(signum, frame):
        logger.info("evento=email_cron_shutdown sinal=%d", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("evento=email_cron_scheduler_start cron=0 %d %d * * (UTC)", minuto, hora)
    scheduler.start()


if __name__ == "__main__":
    main()
