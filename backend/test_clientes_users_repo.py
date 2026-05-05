"""Testes para ClientesUsersRepo (SqliteClientesUsersRepo).

Cobre obter_user_por_site em SqliteClientesUsersRepo.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.clientes_users_repo import SqliteClientesUsersRepo
from auth.tenants_repo import SqliteTenantsRepo


class ObterUserPorSiteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(self._tmp.name) / "db.db")
        # tenants_repo cria schema de sites; clientes_users_repo usa FK para sites
        self.tenants = SqliteTenantsRepo(db_path)
        self.repo = SqliteClientesUsersRepo(db_path)
        self.site = self.tenants.criar_site("acme", "ACME", "production", [])
        self.site2 = self.tenants.criar_site("beta", "Beta", "production", [])

    def tearDown(self):
        self._tmp.cleanup()

    def test_retorna_none_sem_usuarios(self):
        resultado = self.repo.obter_user_por_site(self.site.id)
        self.assertIsNone(resultado)

    def test_retorna_usuario_ativo_existente(self):
        user = self.repo.criar_user(self.site.id, "dono@acme.com", papel="admin")
        resultado = self.repo.obter_user_por_site(self.site.id)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.id, user.id)
        self.assertEqual(resultado.email, "dono@acme.com")

    def test_nao_retorna_usuario_desativado(self):
        user = self.repo.criar_user(self.site.id, "x@acme.com", papel="viewer")
        self.repo.desativar_user(user.id)
        resultado = self.repo.obter_user_por_site(self.site.id)
        self.assertIsNone(resultado)

    def test_retorna_primeiro_ativo_quando_ha_multiplos(self):
        # Cria dois usuários — o primeiro por criado_em deve ser retornado
        user1 = self.repo.criar_user(self.site.id, "primeiro@acme.com", papel="admin")
        user2 = self.repo.criar_user(self.site.id, "segundo@acme.com", papel="viewer")
        resultado = self.repo.obter_user_por_site(self.site.id)
        self.assertIsNotNone(resultado)
        # user1 criado antes de user2, então deve ser retornado
        self.assertEqual(resultado.id, user1.id)

    def test_nao_confunde_sites_distintos(self):
        user_acme = self.repo.criar_user(self.site.id, "dono@acme.com", papel="admin")
        user_beta = self.repo.criar_user(self.site2.id, "dono@beta.com", papel="admin")

        resultado_acme = self.repo.obter_user_por_site(self.site.id)
        resultado_beta = self.repo.obter_user_por_site(self.site2.id)

        self.assertEqual(resultado_acme.id, user_acme.id)
        self.assertEqual(resultado_beta.id, user_beta.id)

    def test_retorna_ativo_ignorando_desativado_anterior(self):
        # desativado não deve ser retornado mesmo existindo antes do ativo
        user_desativado = self.repo.criar_user(self.site.id, "ex@acme.com", papel="viewer")
        self.repo.desativar_user(user_desativado.id)
        user_ativo = self.repo.criar_user(self.site.id, "atual@acme.com", papel="admin")

        resultado = self.repo.obter_user_por_site(self.site.id)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.id, user_ativo.id)


if __name__ == "__main__":
    unittest.main()
