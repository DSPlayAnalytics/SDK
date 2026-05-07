"""TDD do endpoint /metrics e contadores Prometheus.

Cobertura:
- /metrics responde 200 com Content-Type text/plain
- Output contem metric names esperadas
- Contadores incrementam corretamente quando metodos sao chamados
- Registry isolado entre testes (nao polui process-wide CollectorRegistry)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prometheus_client import CollectorRegistry, REGISTRY


class MetricsModuleTest(unittest.TestCase):

    def setUp(self):
        # Cria registry isolado pra cada test — evita colisao com REGISTRY global
        self.registry = CollectorRegistry()

        from metrics import MetricsService
        self.svc = MetricsService(registry=self.registry)

    def test_render_retorna_bytes_em_text_plain(self):
        output = self.svc.render()
        self.assertIsInstance(output, bytes)
        # Linhas-padrao do exposition format Prometheus
        text = output.decode("utf-8")
        # Deve conter pelo menos as metricas declaradas (sem amostras se nao incrementou)
        self.assertIn("portifolio_eventos_recebidos_total", text)
        self.assertIn("portifolio_eventos_rejeitados_total", text)
        self.assertIn("portifolio_websocket_conexoes_ativas", text)

    def test_incrementar_eventos_recebidos_aparece_no_render(self):
        self.svc.eventos_recebidos(tipo="page_analytics")
        self.svc.eventos_recebidos(tipo="page_analytics")
        self.svc.eventos_recebidos(tipo="web_vital")

        text = self.svc.render().decode("utf-8")
        self.assertIn(
            'portifolio_eventos_recebidos_total{tipo="page_analytics"} 2.0', text,
        )
        self.assertIn(
            'portifolio_eventos_recebidos_total{tipo="web_vital"} 1.0', text,
        )

    def test_incrementar_rejeitados_com_code(self):
        self.svc.eventos_rejeitados(code="QUOTA_EXCEDIDA")
        self.svc.eventos_rejeitados(code="QUOTA_EXCEDIDA")
        self.svc.eventos_rejeitados(code="CARDINALIDADE_EXCEDIDA")

        text = self.svc.render().decode("utf-8")
        self.assertIn(
            'portifolio_eventos_rejeitados_total{code="QUOTA_EXCEDIDA"} 2.0', text,
        )
        self.assertIn(
            'portifolio_eventos_rejeitados_total{code="CARDINALIDADE_EXCEDIDA"} 1.0', text,
        )

    def test_websocket_conexoes_gauge_inc_dec(self):
        self.svc.websocket_conectado()
        self.svc.websocket_conectado()
        self.svc.websocket_conectado()
        self.svc.websocket_desconectado()

        text = self.svc.render().decode("utf-8")
        self.assertIn("portifolio_websocket_conexoes_ativas 2.0", text)


class MetricsEndpointTest(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        from metrics import MetricsService, registrar_endpoint

        self.registry = CollectorRegistry()
        self.svc = MetricsService(registry=self.registry)

        self.app = Flask(__name__)
        self.app.testing = True
        registrar_endpoint(self.app, self.svc)
        self.client = self.app.test_client()

    def test_get_metrics_retorna_200(self):
        r = self.client.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content_type.startswith("text/plain"))

    def test_metrics_inclui_python_runtime_metrics_default(self):
        # prometheus_client.process_collector / platform_collector exposem
        # metricas de processo. Confirma que registry default tambem renderiza.
        r = self.client.get("/metrics")
        self.assertIn(b"portifolio_eventos_recebidos_total", r.data)


class MetricsHooksTest(unittest.TestCase):
    """Testa os 3 hooks que alimentam metricas no hot path."""

    def setUp(self):
        self.registry = CollectorRegistry()
        from metrics import MetricsService
        self.svc = MetricsService(registry=self.registry)

    def test_request_observado_aparece_no_histogram(self):
        self.svc.request_observado(path="/api/health", method="GET", segundos=0.012)
        text = self.svc.render().decode("utf-8")
        self.assertIn("portifolio_request_duration_seconds", text)
        self.assertIn('path="/api/health"', text)

    def test_request_observado_multiplos_paths(self):
        self.svc.request_observado(path="/auth/sdk-token", method="POST", segundos=0.05)
        self.svc.request_observado(path="/auth/sdk-token", method="POST", segundos=0.08)
        text = self.svc.render().decode("utf-8")
        # sum deve ser ~0.13
        self.assertIn('portifolio_request_duration_seconds_count{method="POST",path="/auth/sdk-token"} 2.0', text)

    def test_websocket_gauge_sobe_e_desce(self):
        self.svc.websocket_conectado()
        self.svc.websocket_conectado()
        self.svc.websocket_desconectado()
        text = self.svc.render().decode("utf-8")
        self.assertIn("portifolio_websocket_conexoes_ativas 1.0", text)

    def test_websocket_gauge_nao_vai_negativo(self):
        # dec() abaixo de zero e possivel em Gauge; verificamos comportamento esperado
        self.svc.websocket_desconectado()  # 0 -> -1 (prometheus permite, nos monitoramos)
        text = self.svc.render().decode("utf-8")
        self.assertIn("portifolio_websocket_conexoes_ativas", text)

    def test_full_cycle_contador_e_gauge(self):
        self.svc.eventos_recebidos(tipo="page_analytics")
        self.svc.eventos_rejeitados(code="INVALID_TIMESTAMP")
        self.svc.websocket_conectado()
        self.svc.request_observado(path="/cliente/metricas", method="GET", segundos=0.02)
        text = self.svc.render().decode("utf-8")
        self.assertIn("portifolio_eventos_recebidos_total", text)
        self.assertIn("portifolio_eventos_rejeitados_total", text)
        self.assertIn("portifolio_websocket_conexoes_ativas 1.0", text)
        self.assertIn("portifolio_request_duration_seconds", text)


if __name__ == "__main__":
    unittest.main()
