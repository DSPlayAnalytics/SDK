"""TDD pra alertas de cardinalidade em 80% e 95% do limite.

Cobre:
- Tracker emite nivel='80' quando cardinalidade atinge >=80% e nunca emitiu
  esse nivel pra esse site
- Tracker emite nivel='95' depois de cruzar 95%
- Cada nivel emite UMA UNICA VEZ por restart (anti-spam)
- 100% (rejeicao) tambem emite alerta? NAO — rejeicao ja loga
  CARDINALIDADE_EXCEDIDA. Alertas sao para warning *antes* de bloquear.
- ServicoIngestao consume o alert level e loga em security.log
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingestao.cardinalidade import TrackerCardinalidade


class CardinalidadeAlertasTest(unittest.TestCase):

    def setUp(self):
        self.tracker = TrackerCardinalidade()

    def _adicionar_n_pares(self, site_id, n_distintos, limite):
        """Adiciona n_distintos pares unicos. Retorna ultimo (ok, alerta_nivel)."""
        ok = None
        alerta = None
        for i in range(n_distintos):
            pares = [("page_type", f"/p{i}")]
            ok, _, _ = self.tracker.verificar_e_registrar(site_id, pares, limite)
            alerta = self.tracker.alerta_pendente(site_id, limite)
            if alerta is not None:
                break  # primeiro alerta, ja consumiu
        return ok, alerta

    def test_abaixo_de_80_nao_emite_alerta(self):
        # 79% de 100 = 79 valores
        for i in range(79):
            self.tracker.verificar_e_registrar(
                "site-x", [("page_type", f"/p{i}")], 100,
            )
        self.assertIsNone(self.tracker.alerta_pendente("site-x", 100))

    def test_atinge_80_emite_alerta_de_80(self):
        for i in range(80):
            self.tracker.verificar_e_registrar(
                "site-x", [("page_type", f"/p{i}")], 100,
            )
        self.assertEqual(self.tracker.alerta_pendente("site-x", 100), 80)

    def test_alerta_de_80_e_consumido_apos_emitir(self):
        for i in range(80):
            self.tracker.verificar_e_registrar(
                "site-x", [("page_type", f"/p{i}")], 100,
            )
        self.assertEqual(self.tracker.alerta_pendente("site-x", 100), 80)
        # 2a chamada nao retorna mais (ja foi alertado)
        self.assertIsNone(self.tracker.alerta_pendente("site-x", 100))

    def test_atinge_95_emite_alerta_de_95(self):
        for i in range(95):
            self.tracker.verificar_e_registrar(
                "site-x", [("page_type", f"/p{i}")], 100,
            )
        # primeiro consome o 80 (que cruzou no caminho)
        nivel1 = self.tracker.alerta_pendente("site-x", 100)
        nivel2 = self.tracker.alerta_pendente("site-x", 100)
        # Quando cruzou 95, ja tinha cruzado 80 — duas alertas pendentes
        self.assertIn(80, {nivel1, nivel2})
        self.assertIn(95, {nivel1, nivel2})
        # 3a vez nao tem mais
        self.assertIsNone(self.tracker.alerta_pendente("site-x", 100))

    def test_alerta_isolado_por_site(self):
        for i in range(80):
            self.tracker.verificar_e_registrar(
                "site-a", [("page_type", f"/p{i}")], 100,
            )
        # site-b ainda nao tem nada
        self.assertIsNone(self.tracker.alerta_pendente("site-b", 100))
        self.assertEqual(self.tracker.alerta_pendente("site-a", 100), 80)

    def test_invalidar_site_reseta_alertas(self):
        for i in range(80):
            self.tracker.verificar_e_registrar(
                "site-x", [("page_type", f"/p{i}")], 100,
            )
        self.assertEqual(self.tracker.alerta_pendente("site-x", 100), 80)
        self.tracker.invalidar_site("site-x")
        # Re-cresce, deve emitir 80 de novo
        for i in range(80):
            self.tracker.verificar_e_registrar(
                "site-x", [("page_type", f"/p{i}")], 100,
            )
        self.assertEqual(self.tracker.alerta_pendente("site-x", 100), 80)


if __name__ == "__main__":
    unittest.main()
