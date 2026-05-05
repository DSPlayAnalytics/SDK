"""TDD do CORS dinamico.

Cobre 3 niveis:
1. TenantsRepo.dominio_existe(origin) -> bool — query de existencia global.
2. OriginsDinamicos.permitido(origin) -> bool — combina lista estatica +
   lookup dinamico no repo, com cache TTL pra nao hit DB por request.
3. (Integracao Flask vem em test separado)

Usa SQLite em memoria com schema real (mesmo helper de test_dashboard_auth).
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth.tenants_repo import SqliteTenantsRepo


def _criar_repo(tmpdir: Path) -> SqliteTenantsRepo:
    return SqliteTenantsRepo(str(tmpdir / "tenants.db"))


class DominioExisteTest(unittest.TestCase):
    """Repo level: dominio_existe(origin) procura em TODA a tabela
    site_dominios, nao escopado por site_id (diferente de origin_permitido)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = _criar_repo(Path(self._tmp.name))
        self.site = self.repo.criar_site(
            slug="acme", nome="ACME",
            ambiente="production",
            dominios=["https://acme.com", "https://www.acme.com"],
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_dominio_registrado_retorna_true(self):
        self.assertTrue(self.repo.dominio_existe("https://acme.com"))
        self.assertTrue(self.repo.dominio_existe("https://www.acme.com"))

    def test_dominio_nao_registrado_retorna_false(self):
        self.assertFalse(self.repo.dominio_existe("https://hacker.com"))

    def test_origin_vazio_ou_none_retorna_false(self):
        self.assertFalse(self.repo.dominio_existe(""))
        self.assertFalse(self.repo.dominio_existe(None))

    def test_normaliza_trailing_slash_no_lookup(self):
        # criamos sem barra; lookup deve aceitar com barra (case real do header Origin)
        self.assertTrue(self.repo.dominio_existe("https://acme.com/"))


class OriginsDinamicosTest(unittest.TestCase):
    """Service level: combina static + dynamic + cache TTL."""

    def setUp(self):
        from auth.origins_dinamicos import OriginsDinamicos
        self.repo = MagicMock()
        self.svc = OriginsDinamicos(
            origins_estaticos=["https://app.dsplayground.com.br",
                               "https://dsplayground.com.br"],
            tenants_repo=self.repo,
            ttl_segundos=60,
        )

    def test_origin_estatico_passa_sem_consultar_repo(self):
        self.assertTrue(self.svc.permitido("https://app.dsplayground.com.br"))
        self.repo.dominio_existe.assert_not_called()

    def test_origin_dinamico_consulta_repo(self):
        self.repo.dominio_existe.return_value = True
        self.assertTrue(self.svc.permitido("https://acme.com"))
        self.repo.dominio_existe.assert_called_once_with("https://acme.com")

    def test_origin_dinamico_nao_registrado_retorna_false(self):
        self.repo.dominio_existe.return_value = False
        self.assertFalse(self.svc.permitido("https://hacker.com"))

    def test_cache_evita_segunda_consulta_no_repo(self):
        self.repo.dominio_existe.return_value = True
        self.svc.permitido("https://acme.com")
        self.svc.permitido("https://acme.com")
        self.svc.permitido("https://acme.com")
        # 3 requests, 1 hit no DB
        self.assertEqual(self.repo.dominio_existe.call_count, 1)

    def test_cache_separa_origins_diferentes(self):
        self.repo.dominio_existe.side_effect = lambda o: o == "https://valido.com"
        self.assertTrue(self.svc.permitido("https://valido.com"))
        self.assertFalse(self.svc.permitido("https://invalido.com"))
        # ambos foram consultados
        self.assertEqual(self.repo.dominio_existe.call_count, 2)

    def test_cache_negativo_tambem_funciona(self):
        # Origins NAO registrados tambem cacheiam (evita DDoS via origin
        # spoofado bater DB toda req).
        self.repo.dominio_existe.return_value = False
        self.svc.permitido("https://hacker.com")
        self.svc.permitido("https://hacker.com")
        self.assertEqual(self.repo.dominio_existe.call_count, 1)

    def test_origin_none_ou_vazio_false_sem_consultar(self):
        self.assertFalse(self.svc.permitido(None))
        self.assertFalse(self.svc.permitido(""))
        self.repo.dominio_existe.assert_not_called()

    def test_ttl_expira_e_reconsulta(self):
        from auth.origins_dinamicos import OriginsDinamicos
        agora_fake = [1000.0]
        self.svc = OriginsDinamicos(
            origins_estaticos=[],
            tenants_repo=self.repo,
            ttl_segundos=60,
            agora=lambda: agora_fake[0],
        )
        self.repo.dominio_existe.return_value = True
        self.svc.permitido("https://acme.com")  # cache miss
        self.svc.permitido("https://acme.com")  # cache hit

        agora_fake[0] = 1061.0  # passou 61s, TTL expirou
        self.svc.permitido("https://acme.com")  # cache expira -> miss

        self.assertEqual(self.repo.dominio_existe.call_count, 2)


if __name__ == "__main__":
    unittest.main()
