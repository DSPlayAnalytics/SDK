import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(__file__))

import app as app_module


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "analytics_payload_sintetico.json"


class InfluxDBCapturador:
    def __init__(self):
        self.metricas = []
        self.web_vitals = []

    def write_temporal_metrics_async(self, metrica):
        self.metricas.append(metrica)

    def write_web_vital_async(self, metrica):
        self.web_vitals.append(metrica)


def carregar_payload():
    with FIXTURE_PATH.open(encoding="utf-8") as arquivo:
        return atualizar_timestamps(json.load(arquivo))


def atualizar_timestamps(payload):
    """Mantem duracoes do fixture, mas envia timestamps atuais para simular tempo real."""
    timestamp_final = int(time.time() * 1000)
    timestamp_inicial = timestamp_final - 7000
    payload["timestamp_inicial"] = timestamp_inicial
    payload["timestamp_final"] = timestamp_final

    for sessoes in payload.get("paginas", {}).values():
        for sessao in sessoes:
            offset_inicial = sessao["timestamp_inicial"] - 1760000000000
            offset_final = sessao["timestamp_final"] - 1760000000000
            sessao["timestamp_inicial"] = timestamp_inicial + offset_inicial
            sessao["timestamp_final"] = timestamp_inicial + offset_final
            for evento in sessao.get("eventos", []):
                evento["timestamp"] = timestamp_inicial + (evento["timestamp"] - 1760000000000)

    return payload


class IngestaoAnalyticsSocketIOTest(unittest.TestCase):
    def setUp(self):
        self.influxdb_original = app_module.influxdb_service
        self.servico_influxdb_original = app_module.servico_ingestao.influxdb_service
        self.capturador = InfluxDBCapturador()
        app_module.influxdb_service = self.capturador
        app_module.servico_ingestao.influxdb_service = self.capturador
        app_module.active_sessions.clear()
        app_module.temporal_stats_cache["total_sessions"] = 0
        app_module.temporal_stats_cache["active_sessions"].clear()
        app_module.temporal_stats_cache["realtime_data"].clear()

    def tearDown(self):
        app_module.influxdb_service = self.influxdb_original
        app_module.servico_ingestao.influxdb_service = self.servico_influxdb_original
        app_module.active_sessions.clear()
        app_module.temporal_stats_cache["active_sessions"].clear()
        app_module.temporal_stats_cache["realtime_data"].clear()

    def test_socketio_recebe_payload_sintetico_e_resume_metricas(self):
        cliente = app_module.socketio.test_client(
            app_module.app,
            headers={
                "User-Agent": "analytics-contract-test",
                "Accept-Language": "pt-BR",
            },
        )
        self.assertTrue(cliente.is_connected())
        cliente.get_received()

        payload = carregar_payload()
        cliente.emit("analytics_data", payload)
        eventos = cliente.get_received()
        recebidos = [evento for evento in eventos if evento["name"] == "analytics_received"]

        self.assertEqual(len(recebidos), 1)
        resposta = recebidos[0]["args"][0]

        self.assertEqual(resposta["status"], "success")
        self.assertEqual(resposta["id_registro"], "fixture-analytics-sintetico")
        self.assertEqual(resposta["tipo_envio"], "temporal")
        self.assertEqual(resposta["resumo"]["total_visualizacoes"], 3)
        self.assertEqual(resposta["resumo"]["total_cliques"], 3)
        self.assertEqual(resposta["resumo"]["tempo_total_segundos"], 20)
        self.assertEqual(resposta["resumo"]["duracao_sessao_segundos"], 7)
        self.assertEqual(resposta["resumo"]["paginas_visitadas"], {
            "/": 1,
            "/produto/a": 1,
        })

        metricas_por_pagina = {metrica.page_type: metrica for metrica in self.capturador.metricas}
        self.assertEqual(set(metricas_por_pagina), {"/", "/produto/a"})

        home = metricas_por_pagina["/"]
        self.assertEqual(home.visualizacoes, 2)
        self.assertEqual(home.permanencia_segundos, 12)
        self.assertEqual(home.cliques, 2)
        self.assertEqual(home.scrolls, 1)
        self.assertEqual(home.mouse_moves, 3)
        self.assertEqual(home.toques, 1)
        self.assertEqual(home.hovers, 1)
        self.assertEqual(home.exposicoes, 1)

        produto = metricas_por_pagina["/produto/a"]
        self.assertEqual(produto.visualizacoes, 1)
        self.assertEqual(produto.permanencia_segundos, 8)
        self.assertEqual(produto.cliques, 1)
        self.assertEqual(produto.scrolls, 2)
        self.assertEqual(produto.mouse_moves, 0)
        self.assertEqual(produto.toques, 0)
        self.assertEqual(produto.exposicoes, 1)

        self.assertEqual(len(self.capturador.web_vitals), 1)
        vital = self.capturador.web_vitals[0]
        self.assertEqual(vital.nome, "LCP")
        self.assertEqual(vital.valor, 1800)
        self.assertEqual(vital.rating, "good")
        self.assertEqual(vital.page_type, "/")

        cliente.disconnect()


if __name__ == "__main__":
    unittest.main()
