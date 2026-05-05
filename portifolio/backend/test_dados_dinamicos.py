import unittest
import os
import sys

sys.path.append(os.path.dirname(__file__))

from dto.Dados import HeatmapDados
from influxdb_service import (
    create_temporal_metric_from_heatmap,
    create_web_vitals_from_heatmap,
)


def pagina_dados(**sobrescritas):
    dados = {
        "eventos": [],
        "visualizacoes": 0,
        "segundos": 0,
        "timestamp_inicial": None,
        "timestamp_final": None,
    }
    dados.update(sobrescritas)
    return dados


class HeatmapDadosDinamicosTest(unittest.TestCase):
    def test_from_dict_aceita_paginas_dinamicas_sem_chaves_predefinidas(self):
        dados = HeatmapDados.from_dict({
            "id_registro": "registro-teste",
            "paginas": {
                "/blog/artigo": [
                    pagina_dados(
                        visualizacoes=2,
                        segundos=15,
                        eventos=[
                            {"tipo": "click", "timestamp": 1000, "dados": {"x": 10, "y": 20}},
                        ],
                    )
                ]
            },
        })

        self.assertEqual(dados.id_registro, "registro-teste")
        self.assertEqual(len(dados.paginas["/blog/artigo"]), 1)
        self.assertEqual(list(dados.paginas.keys()), ["/blog/artigo"])
        self.assertEqual(dados.get_total_visualizacoes(), 2)
        self.assertEqual(dados.get_total_cliques(), 1)
        self.assertEqual(dados.get_total_tempo_segundos(), 15)

    def test_from_dict_ignora_chaves_predefinidas_fora_do_mapa_paginas(self):
        dados = HeatmapDados.from_dict({
            "home": [pagina_dados(visualizacoes=1, segundos=5)],
            "about": [pagina_dados(visualizacoes=2, segundos=10)],
        })

        self.assertEqual(dados.paginas, {})
        self.assertEqual(dados.get_total_visualizacoes(), 0)
        self.assertEqual(dados.get_total_tempo_segundos(), 0)


class MetricasTemporaisDinamicasTest(unittest.TestCase):
    def test_cria_metricas_agrupando_por_tipo_de_evento(self):
        metricas = create_temporal_metric_from_heatmap(
            session_id="sessao-teste",
            heatmap_data={
                "paginas": {
                    "/blog/artigo": [
                        pagina_dados(
                            visualizacoes=3,
                            segundos=20,
                            eventos=[
                                {"tipo": "click", "timestamp": 1000, "dados": {}},
                                {"tipo": "scroll_depth", "timestamp": 1000, "dados": {"marco": 25}},
                                {"tipo": "mouse_move", "timestamp": 1000, "dados": {}},
                                {"tipo": "touch", "timestamp": 1000, "dados": {}},
                                {"tipo": "hover", "timestamp": 1000, "dados": {}},
                                {"tipo": "element_exposure", "timestamp": 1000, "dados": {}},
                                {"tipo": "custom", "timestamp": 1000, "dados": {"nome": "x"}},
                            ],
                        )
                    ]
                }
            },
            user_agent="teste",
            ip_address="127.0.0.1",
        )

        self.assertEqual(len(metricas), 1)
        metrica = metricas[0]
        self.assertEqual(metrica.session_id, "sessao-teste")
        self.assertEqual(metrica.page_type, "/blog/artigo")
        self.assertEqual(metrica.permanencia_segundos, 20)
        self.assertEqual(metrica.visualizacoes, 3)
        self.assertEqual(metrica.cliques, 1)
        self.assertEqual(metrica.scrolls, 1)
        self.assertEqual(metrica.mouse_moves, 1)
        self.assertEqual(metrica.toques, 1)
        self.assertEqual(metrica.hovers, 1)
        self.assertEqual(metrica.exposicoes, 1)
        self.assertEqual(metrica.custom_events, 1)

    def test_ignora_chaves_predefinidas_fora_do_mapa_paginas(self):
        metricas = create_temporal_metric_from_heatmap(
            session_id="sessao-teste",
            heatmap_data={
                "home": [pagina_dados(visualizacoes=1, segundos=5)],
            },
        )

        self.assertEqual(metricas, [])


class WebVitalsDinamicosTest(unittest.TestCase):
    def test_extrai_web_vitals_dos_eventos_por_pagina(self):
        vitals = create_web_vitals_from_heatmap(
            session_id="sessao-teste",
            heatmap_data={
                "paginas": {
                    "/": [
                        pagina_dados(eventos=[
                            {"tipo": "web_vital", "timestamp": 1000,
                             "dados": {"nome": "LCP", "valor": 1800, "rating": "good", "id": "v3-1"}},
                            {"tipo": "web_vital", "timestamp": 2000,
                             "dados": {"nome": "CLS", "valor": 0.05}},
                            {"tipo": "click", "timestamp": 3000, "dados": {}},
                        ])
                    ]
                }
            },
            user_agent="ua-teste",
        )

        self.assertEqual(len(vitals), 2)
        self.assertEqual(vitals[0].nome, "LCP")
        self.assertEqual(vitals[0].valor, 1800)
        self.assertEqual(vitals[0].rating, "good")
        self.assertEqual(vitals[0].metric_id, "v3-1")
        self.assertEqual(vitals[1].nome, "CLS")
        self.assertEqual(vitals[1].valor, 0.05)
        self.assertIsNone(vitals[1].rating)


if __name__ == "__main__":
    unittest.main()
