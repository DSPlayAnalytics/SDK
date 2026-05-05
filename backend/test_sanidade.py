"""Testes minimos de sanidade: health endpoints por camada,
comportamento com InfluxDB desabilitado e resiliencia a erro de Influx.
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(__file__))

import app as app_module


def _ts_agora() -> tuple[int, int]:
    """Timestamps validos na janela de plausibilidade [server_time-24h, +5min]."""
    agora_ms = int(time.time() * 1000)
    return agora_ms - 5000, agora_ms


class SanidadeHealthAppTest(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_health_app_responde_healthy(self):
        resposta = self.client.get('/health/app')
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.get_json()
        self.assertEqual(dados['status'], 'healthy')
        self.assertIn('detalhe', dados)

    def test_health_socketio_responde_healthy(self):
        resposta = self.client.get('/health/socketio')
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.get_json()
        self.assertEqual(dados['status'], 'healthy')


class SanidadeHealthInfluxDBTest(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.influxdb_original = app_module.influxdb_service

    def tearDown(self):
        app_module.influxdb_service = self.influxdb_original

    def test_health_influxdb_ausente_retorna_unavailable(self):
        app_module.influxdb_service = None
        resposta = self.client.get('/health/influxdb')
        self.assertEqual(resposta.status_code, 503)
        dados = resposta.get_json()
        self.assertEqual(dados['status'], 'unavailable')

    def test_health_influxdb_saudavel(self):
        fake = MagicMock()
        fake.is_healthy.return_value = True
        app_module.influxdb_service = fake
        resposta = self.client.get('/health/influxdb')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json()['status'], 'healthy')

    def test_health_influxdb_degradado(self):
        fake = MagicMock()
        fake.is_healthy.return_value = False
        app_module.influxdb_service = fake
        resposta = self.client.get('/health/influxdb')
        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.get_json()['status'], 'degraded')


class SanidadeIngestaoResilienteTest(unittest.TestCase):
    def test_servico_sem_influxdb_nao_derruba_ingestao(self):
        from ingestao.servico_ingestao import ServicoIngestao
        from ingestao.idempotencia import resetar_tudo
        resetar_tudo()

        ti, tf = _ts_agora()
        servico = ServicoIngestao(influxdb_service=None)
        resumo = servico.ingerir(
            session_id='s1',
            data={
                'id_registro': 'sanidade-sem-influx',
                'app_id': 'teste',
                'ambiente': 'production',
                'timestamp_inicial': ti,
                'timestamp_final': tf,
                'paginas': {},
            },
        )
        self.assertEqual(resumo.status, 'success')

    def test_servico_com_influxdb_falho_nao_derruba_ingestao(self):
        from ingestao.servico_ingestao import ServicoIngestao
        from ingestao.idempotencia import resetar_tudo
        resetar_tudo()

        fake = MagicMock()
        fake.write_temporal_metrics_async.side_effect = RuntimeError('influx caiu')
        servico = ServicoIngestao(influxdb_service=fake)

        ti, tf = _ts_agora()
        resumo = servico.ingerir(
            session_id='s1',
            data={
                'id_registro': 'sanidade-com-influx-falho',
                'app_id': 'teste',
                'ambiente': 'production',
                'timestamp_inicial': ti,
                'timestamp_final': tf,
                'paginas': {'/': [{'eventos': [], 'visualizacoes': 1, 'segundos': 3,
                                    'timestamp_inicial': ti, 'timestamp_final': tf}]},
            },
        )
        self.assertEqual(resumo.status, 'success')


if __name__ == '__main__':
    unittest.main()
