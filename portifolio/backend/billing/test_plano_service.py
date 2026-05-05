"""Testes TDD para billing.plano_service.aplicar_plano.

Usa SqliteTenantsRepo em disco temporario — sem mocks para repositorio,
o que testa a integracao real com o schema SQLite.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.tenants_repo import SqliteTenantsRepo
from billing.plano_service import PLANO_DEFAULTS, aplicar_plano


class AplicarPlanoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))
        self.site = self.repo.criar_site(
            slug="teste", nome="Site Teste", ambiente="test",
            dominios=["https://teste.example.com"], plano="free",
        )

    def tearDown(self):
        self._tmp.cleanup()

    # 1. Plano invalido -> ValueError
    def test_plano_invalido_levanta_value_error(self):
        with self.assertRaises(ValueError):
            aplicar_plano(self.site.id, "premium", self.repo)

    # 2. Site nao existe -> LookupError
    def test_site_inexistente_levanta_lookup_error(self):
        with self.assertRaises(LookupError):
            aplicar_plano("00000000-0000-0000-0000-000000000000", "free", self.repo)

    # 3. Mesmo plano -> retorna False, quota nao muda
    def test_mesmo_plano_retorna_false(self):
        # Garante quota atual do plano free
        self.repo.atualizar_quota(
            self.site.id,
            eventos_por_dia=PLANO_DEFAULTS["free"]["eventos_por_dia"],
            eventos_por_minuto=PLANO_DEFAULTS["free"]["eventos_por_minuto"],
            retencao_dias=PLANO_DEFAULTS["free"]["retencao_dias"],
        )
        quota_antes = self.repo.obter_quota(self.site.id)
        resultado = aplicar_plano(self.site.id, "free", self.repo)
        self.assertFalse(resultado)
        quota_depois = self.repo.obter_quota(self.site.id)
        self.assertEqual(quota_antes.eventos_por_dia, quota_depois.eventos_por_dia)
        self.assertEqual(quota_antes.eventos_por_minuto, quota_depois.eventos_por_minuto)
        self.assertEqual(quota_antes.retencao_dias, quota_depois.retencao_dias)

    # 4. Upgrade free->pro -> True, quota atualizada
    def test_upgrade_free_para_pro(self):
        resultado = aplicar_plano(self.site.id, "pro", self.repo)
        self.assertTrue(resultado)
        quota = self.repo.obter_quota(self.site.id)
        self.assertEqual(quota.eventos_por_dia, PLANO_DEFAULTS["pro"]["eventos_por_dia"])
        self.assertEqual(quota.eventos_por_minuto, PLANO_DEFAULTS["pro"]["eventos_por_minuto"])
        self.assertEqual(quota.retencao_dias, PLANO_DEFAULTS["pro"]["retencao_dias"])
        site_atualizado = self.repo.obter_site(self.site.id)
        self.assertEqual(site_atualizado.plano, "pro")

    # 5. Downgrade pro->free -> True, quota atualizada
    def test_downgrade_pro_para_free(self):
        # Primeiro sobe para pro
        aplicar_plano(self.site.id, "pro", self.repo)
        # Depois desce para free
        resultado = aplicar_plano(self.site.id, "free", self.repo)
        self.assertTrue(resultado)
        quota = self.repo.obter_quota(self.site.id)
        self.assertEqual(quota.eventos_por_dia, PLANO_DEFAULTS["free"]["eventos_por_dia"])
        self.assertEqual(quota.eventos_por_minuto, PLANO_DEFAULTS["free"]["eventos_por_minuto"])
        self.assertEqual(quota.retencao_dias, PLANO_DEFAULTS["free"]["retencao_dias"])
        site_atualizado = self.repo.obter_site(self.site.id)
        self.assertEqual(site_atualizado.plano, "free")

    # 6. Idempotencia: 2x mesmo plano -> segunda retorna False
    def test_idempotencia_segunda_chamada_retorna_false(self):
        primeira = aplicar_plano(self.site.id, "pro", self.repo)
        self.assertTrue(primeira)
        segunda = aplicar_plano(self.site.id, "pro", self.repo)
        self.assertFalse(segunda)


if __name__ == "__main__":
    unittest.main()
