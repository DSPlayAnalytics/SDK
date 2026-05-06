"""Scheduler do archiver — logica pura + binding APScheduler.

Logica em `executar_rodada_diaria` recebe lista de sites, archiver, r2 e
referencia de tempo. Sem I/O direto — cada dependencia e injetada.

Binding em `iniciar_scheduler_diario` configura BackgroundScheduler com
cron 03:00 UTC e mantem processo vivo. Esse e o entrypoint do container
sidecar (chamado por `main.py`).
"""
import gzip
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

logger = logging.getLogger(__name__)

# Gzip de string vazia tem ~20 bytes (header + 0-length body + CRC32+ISIZE).
# Threshold conservador: se decomprimido for 0, pulamos upload.
def _e_payload_vazio(gzip_bytes: bytes) -> bool:
    try:
        return len(gzip.decompress(gzip_bytes)) == 0
    except Exception:
        return False


@dataclass(frozen=True)
class SiteArquivavel:
    """View read-only do site pra rodada do archiver. Construida pelo SitesRepo."""
    slug: str
    plano: str
    retencao_dias: int


@dataclass
class ResumoRodada:
    processados: int = 0
    pulados_free: int = 0
    falhas: int = 0
    vazios: int = 0
    detalhes: List[str] = field(default_factory=list)


def executar_rodada_diaria(
    sites: Iterable[SiteArquivavel],
    archiver,                 # ArchiverService
    r2,                       # R2Client
    agora_utc: datetime,
) -> ResumoRodada:
    """Itera sites e exporta a janela do dia que esta prestes a expirar.

    Janela exportada: `[agora - retencao - 1d, agora - retencao]`. O `dia`
    da chave R2 e `agora.date() - retencao - 1d` (vespera de expirar).

    Falhas em um site nao param o resto — log + contador + segue.
    """
    resumo = ResumoRodada()

    for site in sites:
        if site.plano == 'free':
            resumo.pulados_free += 1
            logger.info(
                f'evento=archive_skip motivo=plano_free slug={site.slug}'
            )
            continue

        # janela = calendar day prestes a expirar nas proximas 24h.
        # Ex: retencao=30d, agora=2026-05-01 → dia 2026-04-01 (= agora.date() - 30d).
        # Dado de 2026-04-01 vai sumir entre agora e o cron de amanha — arquiva
        # antes. Se o cron falhar 1 dia, perdemos esse dia mas pegamos o
        # proximo na rodada seguinte.
        dia_a_exportar = (agora_utc - timedelta(days=site.retencao_dias)).date()
        start = datetime.combine(dia_a_exportar, datetime.min.time(), tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        try:
            payload = archiver.export_window(
                slug=site.slug,
                start=start,
                end=end,
            )
        except Exception as erro:
            resumo.falhas += 1
            resumo.detalhes.append(f'{site.slug}: export erro={erro}')
            logger.error(
                f'evento=archive_export_falhou slug={site.slug} erro={erro!r}'
            )
            continue

        if _e_payload_vazio(payload):
            resumo.vazios += 1
            logger.info(
                f'evento=archive_skip motivo=sem_dados slug={site.slug} dia={dia_a_exportar}'
            )
            continue

        try:
            key = r2.upload(slug=site.slug, dia=dia_a_exportar, body=payload)
        except Exception as erro:
            resumo.falhas += 1
            resumo.detalhes.append(f'{site.slug}: upload erro={erro}')
            logger.error(
                f'evento=archive_upload_falhou slug={site.slug} dia={dia_a_exportar} erro={erro!r}'
            )
            continue

        resumo.processados += 1
        logger.info(
            f'evento=archive_ok slug={site.slug} dia={dia_a_exportar} key={key} bytes={len(payload)}'
        )

    logger.info(
        f'evento=archive_rodada_concluida processados={resumo.processados} '
        f'pulados_free={resumo.pulados_free} falhas={resumo.falhas} vazios={resumo.vazios}'
    )
    return resumo
