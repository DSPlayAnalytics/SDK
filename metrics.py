"""Metricas Prometheus do backend.

Expoe `/metrics` no Flask app + helpers pra incrementar contadores no
hot path de ingestao. Registry isolado pra permitir injecao em tests.

Metricas (sec D.2 plano-backend):
  portifolio_eventos_recebidos_total{tipo=...}      Counter — eventos validados+persistidos
  portifolio_eventos_rejeitados_total{code=...}     Counter — eventos descartados (com motivo)
  portifolio_websocket_conexoes_ativas              Gauge — conexoes Socket.IO ativas
  portifolio_request_duration_seconds{path=...}     Histogram — latencia de requests HTTP
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from flask import Flask, Response


class MetricsService:
    """Encapsula contadores + render. Registry injetavel pra teste isolado."""

    def __init__(self, registry: CollectorRegistry):
        self._registry = registry

        self._eventos_recebidos = Counter(
            "portifolio_eventos_recebidos_total",
            "Eventos analytics recebidos e persistidos com sucesso.",
            labelnames=("tipo",),
            registry=registry,
        )
        self._eventos_rejeitados = Counter(
            "portifolio_eventos_rejeitados_total",
            "Eventos analytics rejeitados (validacao, quota, cardinalidade, etc).",
            labelnames=("code",),
            registry=registry,
        )
        self._ws_conexoes = Gauge(
            "portifolio_websocket_conexoes_ativas",
            "Conexoes Socket.IO ativas no momento.",
            registry=registry,
        )
        self._request_duration = Histogram(
            "portifolio_request_duration_seconds",
            "Latencia de requests HTTP por path.",
            labelnames=("path", "method"),
            registry=registry,
        )

    # --- API publica de incremento ---

    def eventos_recebidos(self, *, tipo: str) -> None:
        self._eventos_recebidos.labels(tipo=tipo).inc()

    def eventos_rejeitados(self, *, code: str) -> None:
        self._eventos_rejeitados.labels(code=code).inc()

    def websocket_conectado(self) -> None:
        self._ws_conexoes.inc()

    def websocket_desconectado(self) -> None:
        self._ws_conexoes.dec()

    def request_observado(self, *, path: str, method: str, segundos: float) -> None:
        self._request_duration.labels(path=path, method=method).observe(segundos)

    # --- Render ---

    def render(self) -> bytes:
        """Retorna exposition format do Prometheus (text/plain)."""
        return generate_latest(self._registry)

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST


def registrar_endpoint(app: Flask, svc: MetricsService) -> None:
    """Registra GET /metrics no Flask app.

    Idempotente: chamar duas vezes nao causa erro (usa endpoint name unico).
    """

    @app.route("/metrics", methods=["GET"], endpoint="prometheus_metrics")
    def metrics_endpoint():
        return Response(svc.render(), mimetype=svc.content_type)


# --- Singleton de processo ---

_metrics_singleton = None


def obter_metrics() -> MetricsService:
    """Singleton padrao usando o registry global do prometheus_client.

    Usar em hot path (servico_ingestao etc.) sem precisar passar a instancia
    pra cada chamador. Tests devem instanciar MetricsService(registry=...) direto.
    """
    global _metrics_singleton
    if _metrics_singleton is None:
        from prometheus_client import REGISTRY
        _metrics_singleton = MetricsService(registry=REGISTRY)
    return _metrics_singleton


def resetar_metrics() -> None:
    """Apenas para testes — reseta o singleton."""
    global _metrics_singleton
    _metrics_singleton = None


__all__ = [
    "MetricsService",
    "registrar_endpoint",
    "obter_metrics",
    "resetar_metrics",
]
