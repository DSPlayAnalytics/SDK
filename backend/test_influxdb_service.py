"""Tests pra construcao de Points InfluxDB via InfluxDBService.

Schema 1.2 (SDK v0.4): user_bucket / group_bucket viram TAG (cardinalidade
controlada, 256 bins) e user_id / group_id viram FIELD (cardinalidade zero,
exibicao). Decisao D1 opcao C — ver memoria.

Stratery: stub do write_api captura o Point antes de ir pra rede.
Inspecionamos `_tags` / `_fields` (atributos publicos da lib influxdb-client).
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.append(os.path.dirname(__file__))

from influxdb_service import (
    ConversionEventMetric,
    CustomEventMetric,
    InfluxDBService,
    TemporalMetric,
    WebVitalMetric,
    create_conversion_events_from_heatmap,
    create_custom_events_from_heatmap,
)


class StubWriteApi:
    """Captura `write(bucket, record)` para inspecao em teste."""

    def __init__(self):
        self.chamadas = []

    def write(self, bucket, record):
        self.chamadas.append((bucket, record))


def _servico_stub() -> InfluxDBService:
    """Cria InfluxDBService sem conectar — flip enabled + write_api stub."""
    s = InfluxDBService(url="http://test", token="t", org="o",
                        bucket="default", enabled=False)
    s.enabled = True
    s.write_api = StubWriteApi()
    return s


def _metric_temporal(**overrides) -> TemporalMetric:
    base = dict(
        session_id="s1",
        page_type="/",
        permanencia_segundos=5.0,
        visualizacoes=1,
        timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        app_id="acme",
        ambiente="production",
    )
    base.update(overrides)
    return TemporalMetric(**base)


def _metric_web_vital(**overrides) -> WebVitalMetric:
    base = dict(
        session_id="s1",
        page_type="/",
        nome="LCP",
        valor=1800.0,
        timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        app_id="acme",
        ambiente="production",
    )
    base.update(overrides)
    return WebVitalMetric(**base)


def _metric_custom(**overrides) -> CustomEventMetric:
    base = dict(
        session_id="s1",
        page_type="/",
        nome="botao",
        propriedades={},
        timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        app_id="acme",
        ambiente="production",
    )
    base.update(overrides)
    return CustomEventMetric(**base)


# =============================================================
# TemporalMetric -> Point page_analytics
# =============================================================

class TemporalMetricPointTests(unittest.TestCase):

    def test_user_bucket_vai_pra_tag(self):
        s = _servico_stub()
        m = _metric_temporal(user_id="u-42", user_bucket="b042")
        ok = s.write_temporal_metrics(m)
        self.assertTrue(ok)
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._tags.get("user_bucket"), "b042")

    def test_user_id_vai_pra_field_nao_tag(self):
        # Anti-cardinality-explosion: user_id NAO pode ser tag em InfluxDB OSS.
        s = _servico_stub()
        m = _metric_temporal(user_id="u-42", user_bucket="b042")
        s.write_temporal_metrics(m)
        _, point = s.write_api.chamadas[0]
        self.assertNotIn("user_id", point._tags)
        self.assertEqual(point._fields.get("user_id"), "u-42")

    def test_group_bucket_e_id_simetricos_a_user(self):
        s = _servico_stub()
        m = _metric_temporal(group_id="acme-corp", group_bucket="b201")
        s.write_temporal_metrics(m)
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._tags.get("group_bucket"), "b201")
        self.assertEqual(point._fields.get("group_id"), "acme-corp")
        self.assertNotIn("group_id", point._tags)

    def test_sem_identidade_nao_adiciona_tag_nem_field(self):
        # Crucial: ausencia de user_id nao pode virar tag "None" ou field "".
        # Garante forward-compat com Pontos antigos (queries Flux com r.user_bucket
        # filtram com `exists` semantica).
        s = _servico_stub()
        m = _metric_temporal()  # sem user_id/group_id
        s.write_temporal_metrics(m)
        _, point = s.write_api.chamadas[0]
        self.assertNotIn("user_bucket", point._tags)
        self.assertNotIn("group_bucket", point._tags)
        self.assertNotIn("user_id", point._fields)
        self.assertNotIn("group_id", point._fields)


# =============================================================
# WebVitalMetric -> Point web_vitals
# =============================================================

class WebVitalPointTests(unittest.TestCase):

    def test_user_bucket_vai_pra_tag(self):
        s = _servico_stub()
        m = _metric_web_vital(user_id="u-perf", user_bucket="b100")
        s.write_web_vital(m)
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._tags.get("user_bucket"), "b100")
        self.assertEqual(point._fields.get("user_id"), "u-perf")
        self.assertNotIn("user_id", point._tags)

    def test_sem_identidade_omite(self):
        s = _servico_stub()
        s.write_web_vital(_metric_web_vital())
        _, point = s.write_api.chamadas[0]
        self.assertNotIn("user_bucket", point._tags)
        self.assertNotIn("user_id", point._fields)


# =============================================================
# CustomEventMetric -> Point custom_events
# =============================================================

class CustomEventPointTests(unittest.TestCase):

    def test_user_bucket_e_group_simetricos(self):
        s = _servico_stub()
        m = _metric_custom(
            user_id="u-buy", user_bucket="b007",
            group_id="org-z", group_bucket="b212",
        )
        s.write_custom_event(m)
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._tags.get("user_bucket"), "b007")
        self.assertEqual(point._tags.get("group_bucket"), "b212")
        self.assertEqual(point._fields.get("user_id"), "u-buy")
        self.assertEqual(point._fields.get("group_id"), "org-z")

    def test_propriedades_continuam_funcionando(self):
        # Regression: nao quebrar fluxo existente de propriedades por evento.
        s = _servico_stub()
        m = _metric_custom(propriedades={"button": "comprar"})
        s.write_custom_event(m)
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._fields.get("prop_button"), "comprar")


def _metric_conversion(**overrides) -> ConversionEventMetric:
    base = dict(
        session_id="s1",
        page_type="/",
        nome="__purchase",
        tipo="purchase",
        propriedades={},
        timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        app_id="acme",
        ambiente="production",
    )
    base.update(overrides)
    return ConversionEventMetric(**base)


# =============================================================
# ConversionEventMetric -> Point conversion_events
# =============================================================

class ConversionEventPointTests(unittest.TestCase):

    def test_escreve_no_measurement_conversion_events(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion())
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._name, "conversion_events")

    def test_tipo_vai_pra_tag(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion(tipo="purchase"))
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._tags.get("tipo"), "purchase")

    def test_valor_vai_pra_field_float(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion(valor=99.9))
        _, point = s.write_api.chamadas[0]
        self.assertAlmostEqual(point._fields.get("valor"), 99.9)

    def test_moeda_vai_pra_field(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion(moeda="BRL"))
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._fields.get("moeda"), "BRL")

    def test_plano_vai_pra_field(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion(plano="pro"))
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._fields.get("plano"), "pro")

    def test_sem_valor_moeda_plano_nao_adiciona_fields(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion())  # todos None
        _, point = s.write_api.chamadas[0]
        self.assertNotIn("valor", point._fields)
        self.assertNotIn("moeda", point._fields)
        self.assertNotIn("plano", point._fields)

    def test_user_bucket_tag_user_id_field(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion(user_id="u-42", user_bucket="b042"))
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._tags.get("user_bucket"), "b042")
        self.assertEqual(point._fields.get("user_id"), "u-42")
        self.assertNotIn("user_id", point._tags)

    def test_propriedades_extras_como_prop_fields(self):
        s = _servico_stub()
        s.write_conversion_event(_metric_conversion(propriedades={"from": "free", "seats": 5}))
        _, point = s.write_api.chamadas[0]
        self.assertEqual(point._fields.get("prop_from"), "free")
        self.assertAlmostEqual(point._fields.get("prop_seats"), 5.0)


# =============================================================
# create_custom_events_from_heatmap filtra __ prefix
# =============================================================

def _heatmap_com_eventos(*eventos):
    """Helper: monta heatmap_data com lista de eventos na pagina '/'."""
    agora = 1714750000000
    return {
        "app_id": "acme",
        "ambiente": "production",
        "paginas": {
            "/": [{
                "eventos": list(eventos),
                "visualizacoes": 1,
                "segundos": 5,
                "timestamp_inicial": agora - 5000,
                "timestamp_final": agora,
            }]
        }
    }


class FiltrarEventosIdentidadeTests(unittest.TestCase):

    def test_skip_identidade_eventos_do_pipeline_custom(self):
        """__identify/__group/__reset nao devem entrar em custom_events."""
        heatmap = _heatmap_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {"nome": "__identify", "propriedades": {"user_id": "u-1"}}},
            {"tipo": "custom", "timestamp": 2, "dados": {"nome": "__group", "propriedades": {"group_id": "g-1"}}},
            {"tipo": "custom", "timestamp": 3, "dados": {"nome": "__reset", "propriedades": {}}},
            {"tipo": "custom", "timestamp": 4, "dados": {"nome": "click_normal", "propriedades": {}}},
        )
        result = create_custom_events_from_heatmap("s1", heatmap)
        nomes = [r.nome for r in result]
        self.assertNotIn("__identify", nomes)
        self.assertNotIn("__group", nomes)
        self.assertNotIn("__reset", nomes)
        self.assertIn("click_normal", nomes)

    def test_skip_conversion_eventos_do_pipeline_custom(self):
        """__purchase/__signup/__conversion nao devem ir pra custom_events."""
        heatmap = _heatmap_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {"nome": "__purchase", "propriedades": {"value": 99.9, "currency": "BRL"}}},
            {"tipo": "custom", "timestamp": 2, "dados": {"nome": "__signup", "propriedades": {"plan": "pro"}}},
            {"tipo": "custom", "timestamp": 3, "dados": {"nome": "evento_normal", "propriedades": {}}},
        )
        result = create_custom_events_from_heatmap("s1", heatmap)
        nomes = [r.nome for r in result]
        self.assertNotIn("__purchase", nomes)
        self.assertNotIn("__signup", nomes)
        self.assertIn("evento_normal", nomes)


class CreateConversionEventsTests(unittest.TestCase):

    def test_extrai_purchase_com_valor_e_moeda(self):
        heatmap = _heatmap_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {
                "nome": "__purchase",
                "propriedades": {"value": 49.9, "currency": "BRL"},
            }},
        )
        result = create_conversion_events_from_heatmap("s1", heatmap)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].nome, "__purchase")
        self.assertEqual(result[0].tipo, "purchase")
        self.assertAlmostEqual(result[0].valor, 49.9)
        self.assertEqual(result[0].moeda, "BRL")

    def test_extrai_signup_com_plano(self):
        heatmap = _heatmap_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {
                "nome": "__signup",
                "propriedades": {"plan": "enterprise"},
            }},
        )
        result = create_conversion_events_from_heatmap("s1", heatmap)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tipo, "signup")
        self.assertEqual(result[0].plano, "enterprise")

    def test_extrai_conversion_generica(self):
        heatmap = _heatmap_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {
                "nome": "__conversion",
                "propriedades": {"type": "trial_start", "value": 0},
            }},
        )
        result = create_conversion_events_from_heatmap("s1", heatmap)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tipo, "trial_start")
        self.assertAlmostEqual(result[0].valor, 0.0)

    def test_ignora_identidade_e_eventos_normais(self):
        heatmap = _heatmap_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {"nome": "__identify", "propriedades": {}}},
            {"tipo": "custom", "timestamp": 2, "dados": {"nome": "click", "propriedades": {}}},
            {"tipo": "custom", "timestamp": 3, "dados": {"nome": "__purchase", "propriedades": {"value": 10, "currency": "USD"}}},
        )
        result = create_conversion_events_from_heatmap("s1", heatmap)
        nomes = [r.nome for r in result]
        self.assertEqual(nomes, ["__purchase"])

    def test_sem_conversoes_retorna_lista_vazia(self):
        heatmap = _heatmap_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {"nome": "click", "propriedades": {}}},
        )
        result = create_conversion_events_from_heatmap("s1", heatmap)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
