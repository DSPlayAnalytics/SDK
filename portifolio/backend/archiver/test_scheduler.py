"""TDD do scheduler do archiver.

Logica pura em `executar_rodada_diaria(sites, archiver, r2, agora_utc)`. APScheduler
e responsabilidade do main.py — nao testamos cron timing, so a iteracao + janela.

Janela por site: `[agora - retencao - 1d, agora - retencao]`. O dia exportado
e portanto `agora.date() - retencao - 1d` (vespera de virar expirado).
"""
import gzip
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archiver.scheduler import SiteArquivavel, executar_rodada_diaria


def _payload_gzip_fake(texto: str = 'fake line protocol') -> bytes:
    return gzip.compress(texto.encode('utf-8'))


class SchedulerTest(unittest.TestCase):

    def setUp(self):
        self.archiver = MagicMock()
        self.r2 = MagicMock()
        self.agora = datetime(2026, 5, 1, 3, 0, tzinfo=timezone.utc)

    def test_pula_sites_plano_free(self):
        sites = [
            SiteArquivavel(slug='free-cli', plano='free', retencao_dias=7),
            SiteArquivavel(slug='pago', plano='pequeno', retencao_dias=30),
        ]
        self.archiver.export_window.return_value = _payload_gzip_fake()

        resumo = executar_rodada_diaria(sites, self.archiver, self.r2, self.agora)

        self.assertEqual(resumo.processados, 1)
        self.assertEqual(resumo.pulados_free, 1)
        self.assertEqual(self.archiver.export_window.call_count, 1)
        chamada = self.archiver.export_window.call_args
        self.assertEqual(chamada.kwargs['slug'], 'pago')

    def test_janela_e_dia_anterior_ao_dia_de_expiracao(self):
        # Site retencao=30d em 2026-05-01 — dia que VAI expirar e 2026-04-01.
        # Exportamos esse dia (start=2026-04-01T00, end=2026-04-02T00).
        sites = [SiteArquivavel(slug='cli', plano='medio', retencao_dias=30)]
        self.archiver.export_window.return_value = _payload_gzip_fake()

        executar_rodada_diaria(sites, self.archiver, self.r2, self.agora)

        chamada = self.archiver.export_window.call_args
        self.assertEqual(
            chamada.kwargs['start'],
            datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            chamada.kwargs['end'],
            datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc),
        )

    def test_upload_usa_dia_da_janela_inicial_como_chave(self):
        sites = [SiteArquivavel(slug='cli', plano='pequeno', retencao_dias=7)]
        self.archiver.export_window.return_value = _payload_gzip_fake()

        executar_rodada_diaria(sites, self.archiver, self.r2, self.agora)

        chamada_upload = self.r2.upload.call_args
        self.assertEqual(chamada_upload.kwargs['slug'], 'cli')
        # 2026-05-01 - 7 = 2026-04-24 (dia prestes a expirar)
        from datetime import date
        self.assertEqual(chamada_upload.kwargs['dia'], date(2026, 4, 24))

    def test_continua_apos_falha_em_um_site(self):
        # Falha do site A nao deve impedir B de processar.
        sites = [
            SiteArquivavel(slug='a-falha', plano='medio', retencao_dias=30),
            SiteArquivavel(slug='b-ok', plano='medio', retencao_dias=30),
        ]
        self.archiver.export_window.side_effect = [
            RuntimeError('influx down'),
            _payload_gzip_fake(),
        ]

        resumo = executar_rodada_diaria(sites, self.archiver, self.r2, self.agora)

        self.assertEqual(resumo.processados, 1)
        self.assertEqual(resumo.falhas, 1)
        self.assertEqual(self.r2.upload.call_count, 1)
        # so o b-ok foi uploaded
        self.assertEqual(self.r2.upload.call_args.kwargs['slug'], 'b-ok')

    def test_nao_faz_upload_se_export_retornar_payload_sem_dados(self):
        # Quando o gzip e de string vazia (bucket sem dados na janela), pula
        # upload pra nao poluir R2 com arquivos vazios. Mantemos contadores
        # em vazios separados pra observability.
        sites = [SiteArquivavel(slug='vazio', plano='pequeno', retencao_dias=7)]
        self.archiver.export_window.return_value = gzip.compress(b'')

        resumo = executar_rodada_diaria(sites, self.archiver, self.r2, self.agora)

        self.assertEqual(resumo.processados, 0)
        self.assertEqual(resumo.vazios, 1)
        self.r2.upload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
