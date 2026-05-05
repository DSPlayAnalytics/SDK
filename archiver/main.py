"""Entrypoint do container `analytics-archiver`.

Roda APScheduler com cron diario 03:00 UTC chamando `executar_rodada_diaria`.
Tudo configurado via env vars (12-factor):

  INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG  — leitura do bucket cliente_*
  TENANTS_DATABASE_URL                         — Postgres pra listar sites
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,             — credenciais R2
  R2_SECRET_ACCESS_KEY, R2_BUCKET
  ARCHIVER_CRON_HORA (default 3)               — cron tunable
  ARCHIVER_CRON_MINUTO (default 0)
  ARCHIVER_RUN_ON_START (default false)        — true = roda imediatamente uma
                                                  vez ao boot (debug/backfill)

Logs estruturados (`evento=archive_*`) — mesmo padrao do backend principal.
"""
import logging
import os
import signal
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from influxdb_client import InfluxDBClient

# Caminho relativo pra reusar auth/tenants_repo do backend principal.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.tenants_repo import PostgresTenantsRepo  # noqa: E402

from archiver.r2_client import R2Client
from archiver.scheduler import executar_rodada_diaria
from archiver.service import ArchiverService
from archiver.sites_source import listar_sites_arquivaveis


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s evento_loglevel=%(levelname)s %(message)s',
)
logger = logging.getLogger('archiver.main')


def _env_obrigatoria(nome: str) -> str:
    valor = os.environ.get(nome, '').strip()
    if not valor:
        logger.error(f'evento=archive_boot_falhou motivo=env_ausente var={nome}')
        sys.exit(1)
    return valor


def _construir_dependencias():
    influx = InfluxDBClient(
        url=_env_obrigatoria('INFLUXDB_URL'),
        token=_env_obrigatoria('INFLUXDB_TOKEN'),
        org=_env_obrigatoria('INFLUXDB_ORG'),
        timeout=30000,
    )

    archiver = ArchiverService(
        influx_client=influx,
        org=os.environ['INFLUXDB_ORG'],
    )

    r2 = R2Client(
        access_key_id=_env_obrigatoria('R2_ACCESS_KEY_ID'),
        secret_access_key=_env_obrigatoria('R2_SECRET_ACCESS_KEY'),
        bucket=_env_obrigatoria('R2_BUCKET'),
        endpoint_url=R2Client.endpoint_padrao_r2(_env_obrigatoria('R2_ACCOUNT_ID')),
    )

    tenants_repo = PostgresTenantsRepo(_env_obrigatoria('TENANTS_DATABASE_URL'))
    return archiver, r2, tenants_repo


def _rodar_uma_vez(archiver, r2, tenants_repo) -> None:
    sites = listar_sites_arquivaveis(tenants_repo)
    logger.info(f'evento=archive_rodada_iniciada qtd_sites={len(sites)}')
    executar_rodada_diaria(
        sites=sites,
        archiver=archiver,
        r2=r2,
        agora_utc=datetime.now(tz=timezone.utc),
    )


def main() -> None:
    archiver, r2, tenants_repo = _construir_dependencias()

    if os.environ.get('ARCHIVER_RUN_ON_START', 'false').lower() == 'true':
        logger.info('evento=archive_run_on_start')
        _rodar_uma_vez(archiver, r2, tenants_repo)

    hora = int(os.environ.get('ARCHIVER_CRON_HORA', '3'))
    minuto = int(os.environ.get('ARCHIVER_CRON_MINUTO', '0'))

    scheduler = BlockingScheduler(timezone='UTC')
    scheduler.add_job(
        lambda: _rodar_uma_vez(archiver, r2, tenants_repo),
        trigger='cron',
        hour=hora,
        minute=minuto,
        id='archive_diario',
    )

    # SIGTERM (compose stop) → shutdown graceful do scheduler
    def _shutdown(signum, frame):
        logger.info(f'evento=archive_shutdown sinal={signum}')
        scheduler.shutdown(wait=False)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info(
        f'evento=archive_scheduler_start cron=0 {minuto} {hora} * * (UTC)'
    )
    scheduler.start()


if __name__ == '__main__':
    main()
