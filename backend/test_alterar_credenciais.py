"""TDD pra alterar email e senha do cliente.

Cobre 3 niveis:
1. Repo: atualizar_senha_hash + atualizar_email
2. SessaoService: alterar_senha(user_id, senha_atual, nova_senha) + alterar_email
3. Endpoints: PATCH /cliente/auth/senha + /cliente/auth/email

Validacoes:
- Senha atual obrigatoria (sem isso, attacker com cookie pode trocar tudo)
- Nova senha minimo 8 chars (mesmo do cadastro)
- Email novo unico no banco (UNIQUE em clientes_users.email)
- Email novo formato valido (regex)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth.clientes_users_repo import SqliteClientesUsersRepo
from auth.sessao_service import SessaoService
from auth.tenants_repo import SqliteTenantsRepo


def _preparar(tmpdir: Path):
    db_path = str(tmpdir / "tenants.db")
    tenants = SqliteTenantsRepo(db_path)
    users = SqliteClientesUsersRepo(db_path)
    site = tenants.criar_site(
        slug="acme", nome="ACME", ambiente="development", dominios=[],
    )
    return tenants, users, site.id


class RepoAtualizacoesTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tenants, self.users, self.site_id = _preparar(Path(self._tmp.name))
        # Cria user com senha-hash (nao usa SessaoService aqui pra testar repo isolado)
        from werkzeug.security import generate_password_hash
        self.user = self.users.criar_user(
            self.site_id, "dan@acme.com", papel="admin",
            senha_hash=generate_password_hash("secret-original"),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_atualizar_senha_hash_persiste(self):
        from werkzeug.security import generate_password_hash, check_password_hash
        novo_hash = generate_password_hash("nova-senha-789")
        self.users.atualizar_senha_hash(self.user.id, novo_hash)

        atualizado = self.users.obter_user(self.user.id)
        self.assertTrue(check_password_hash(atualizado.senha_hash, "nova-senha-789"))
        self.assertFalse(check_password_hash(atualizado.senha_hash, "secret-original"))

    def test_atualizar_email_normaliza_lowercase_e_persiste(self):
        self.users.atualizar_email(self.user.id, "Novo@ACME.COM")
        atualizado = self.users.obter_user(self.user.id)
        self.assertEqual(atualizado.email, "novo@acme.com")

    def test_atualizar_email_conflito_unique_levanta(self):
        # outro user com email Y, tenta mudar user1 pra Y
        self.users.criar_user(self.site_id, "outro@acme.com")
        with self.assertRaises(Exception):
            self.users.atualizar_email(self.user.id, "outro@acme.com")


class ServiceAlterarTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tenants, self.users, self.site_id = _preparar(Path(self._tmp.name))
        self.svc = SessaoService(self.users, sessao_ttl_segundos=3600)
        self.user = self.svc.criar_user(
            self.site_id, "dan@acme.com", senha="secret-123", papel="admin",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_alterar_senha_com_senha_atual_correta_atualiza(self):
        ok = self.svc.alterar_senha(self.user.id, "secret-123", "novo-secret-456")
        self.assertTrue(ok)
        # Login antigo nao funciona mais
        self.assertIsNone(self.svc.autenticar_por_senha("dan@acme.com", "secret-123"))
        # Login novo funciona
        novo = self.svc.autenticar_por_senha("dan@acme.com", "novo-secret-456")
        self.assertIsNotNone(novo)

    def test_alterar_senha_com_senha_atual_errada_rejeita(self):
        ok = self.svc.alterar_senha(self.user.id, "errada", "novo-secret-456")
        self.assertFalse(ok)
        # Senha original ainda funciona
        self.assertIsNotNone(self.svc.autenticar_por_senha("dan@acme.com", "secret-123"))

    def test_alterar_senha_nova_curta_rejeita(self):
        # Min 8 chars
        ok = self.svc.alterar_senha(self.user.id, "secret-123", "curta")
        self.assertFalse(ok)

    def test_alterar_email_com_senha_correta_atualiza(self):
        codigo = self.svc.alterar_email(self.user.id, "secret-123", "novo@acme.com")
        self.assertIsNone(codigo)
        # Login com novo email funciona
        novo = self.svc.autenticar_por_senha("novo@acme.com", "secret-123")
        self.assertIsNotNone(novo)

    def test_alterar_email_com_senha_errada_rejeita(self):
        codigo = self.svc.alterar_email(self.user.id, "errada", "novo@acme.com")
        self.assertEqual(codigo, "SENHA_INVALIDA")

    def test_alterar_email_invalido_rejeita(self):
        codigo = self.svc.alterar_email(self.user.id, "secret-123", "nao-tem-arroba")
        self.assertEqual(codigo, "EMAIL_INVALIDO")

    def test_alterar_email_ja_em_uso_rejeita(self):
        self.svc.criar_user(self.site_id, "outro@acme.com", senha="x12345678")
        codigo = self.svc.alterar_email(self.user.id, "secret-123", "outro@acme.com")
        self.assertEqual(codigo, "EMAIL_JA_CADASTRADO")


# ----------------------------------------------------------------------
# Endpoints PATCH /cliente/auth/senha + /cliente/auth/email
# ----------------------------------------------------------------------


def _criar_app(tenants, users, svc):
    from flask import Flask
    from auth import cliente_routes as mod
    app = Flask(__name__)
    mod._svc_instance = svc
    mod._tenants_repo = tenants
    mod._clientes_users_repo = users
    os.environ["COOKIE_SECURE"] = "false"
    app.register_blueprint(mod.cliente_auth_bp)
    app.testing = True
    return app


class EndpointsAlterarTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tenants, self.users, self.site_id = _preparar(Path(self._tmp.name))
        self.svc = SessaoService(self.users, sessao_ttl_segundos=3600)
        self.svc.criar_user(self.site_id, "dan@acme.com", senha="secret-123", papel="admin")
        self.app = _criar_app(self.tenants, self.users, self.svc)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def _login(self):
        r = self.client.post("/cliente/auth/login",
                             json={"email": "dan@acme.com", "senha": "secret-123"})
        self.assertEqual(r.status_code, 200)

    # PATCH /senha
    def test_patch_senha_sem_cookie_401(self):
        r = self.client.patch("/cliente/auth/senha",
                              json={"senha_atual": "secret-123", "nova_senha": "x12345678"})
        self.assertEqual(r.status_code, 401)

    def test_patch_senha_correta_200(self):
        self._login()
        r = self.client.patch("/cliente/auth/senha",
                              json={"senha_atual": "secret-123", "nova_senha": "x12345678"})
        self.assertEqual(r.status_code, 200)

    def test_patch_senha_errada_403(self):
        self._login()
        r = self.client.patch("/cliente/auth/senha",
                              json={"senha_atual": "errada", "nova_senha": "x12345678"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["code"], "SENHA_INVALIDA")

    def test_patch_senha_curta_400(self):
        self._login()
        r = self.client.patch("/cliente/auth/senha",
                              json={"senha_atual": "secret-123", "nova_senha": "abc"})
        self.assertEqual(r.status_code, 400)

    # PATCH /email
    def test_patch_email_sem_cookie_401(self):
        r = self.client.patch("/cliente/auth/email",
                              json={"senha_atual": "secret-123", "novo_email": "novo@x.com"})
        self.assertEqual(r.status_code, 401)

    def test_patch_email_correto_200(self):
        self._login()
        r = self.client.patch("/cliente/auth/email",
                              json={"senha_atual": "secret-123", "novo_email": "novo@acme.com"})
        self.assertEqual(r.status_code, 200)

    def test_patch_email_senha_errada_403(self):
        self._login()
        r = self.client.patch("/cliente/auth/email",
                              json={"senha_atual": "errada", "novo_email": "novo@acme.com"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["code"], "SENHA_INVALIDA")

    def test_patch_email_invalido_400(self):
        self._login()
        r = self.client.patch("/cliente/auth/email",
                              json={"senha_atual": "secret-123", "novo_email": "sem-arroba"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "EMAIL_INVALIDO")


if __name__ == "__main__":
    unittest.main()
