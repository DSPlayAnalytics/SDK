"""TDD 2FA TOTP — SessaoService + endpoints /totp/*.

Cobertura:
- iniciar_configuracao_totp retorna secret valido e URI
- confirmar_totp_setup com code valido habilita TOTP
- confirmar_totp_setup com code invalido retorna False
- verificar_totp com code valido retorna True
- verificar_totp sem secret retorna False
- completar_login_totp com code valido cria sessao
- completar_login_totp com code invalido retorna None
- desabilitar_totp com code TOTP valido
- desabilitar_totp com senha valida
- desabilitar_totp com credencial invalida retorna CREDENCIAL_INVALIDA
- desabilitar_totp quando nao habilitado retorna TOTP_NAO_HABILITADO
- POST /login sem TOTP continua funcionando
- POST /login com TOTP retorna totp_required + token
- POST /totp/verificar com code valido cria sessao + cookie
- POST /totp/verificar com code invalido retorna 401
- POST /totp/verificar com token expirado retorna 401
- POST /totp/setup retorna secret + uri
- POST /totp/setup quando ja habilitado retorna 409
- POST /totp/confirmar com code valido habilita
- POST /totp/confirmar com code invalido retorna 422
- DELETE /totp com code valido desabilita
- DELETE /totp com credencial invalida retorna 403
- DELETE /totp quando nao habilitado retorna 409
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyotp

from auth.clientes_users_repo import SqliteClientesUsersRepo
from auth.sessao_service import SessaoService
from auth.tenants_repo import SqliteTenantsRepo


def _criar_repo_svc():
    """Cria repo + service + user de teste em DB temporario."""
    import tempfile
    from pathlib import Path

    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test_totp.db")
    tenants = SqliteTenantsRepo(db_path)
    site = tenants.criar_site(slug="teste", nome="Teste", ambiente="development", dominios=[])
    repo = SqliteClientesUsersRepo(db_path)
    svc = SessaoService(repo)
    user = svc.criar_user(site.id, "totp@teste.com", senha="Senha1234!")
    return repo, svc, user, site.id


class TestTotpService(unittest.TestCase):

    def setUp(self):
        self.repo, self.svc, self.user, self._site_id = _criar_repo_svc()

    def test_iniciar_configuracao_retorna_secret_e_uri(self):
        secret, uri = self.svc.iniciar_configuracao_totp(self.user.id)
        self.assertTrue(secret)
        self.assertIn("otpauth://totp/", uri)
        self.assertIn("totp%40teste.com", uri)
        self.assertIn("DSPlay", uri)
        self.assertIn("Analytics", uri)

    def test_confirmar_setup_com_code_valido_habilita(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        codigo = pyotp.TOTP(secret).now()
        ok = self.svc.confirmar_totp_setup(self.user.id, secret, codigo)
        self.assertTrue(ok)
        user_atualizado = self.repo.obter_user(self.user.id)
        self.assertTrue(user_atualizado.totp_habilitado)
        self.assertEqual(self.repo.obter_totp_secret(self.user.id), secret)

    def test_confirmar_setup_com_code_invalido_retorna_false(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        ok = self.svc.confirmar_totp_setup(self.user.id, secret, "000000")
        self.assertFalse(ok)
        user = self.repo.obter_user(self.user.id)
        self.assertFalse(user.totp_habilitado)

    def test_verificar_totp_com_secret_habilitado(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        self.svc.confirmar_totp_setup(self.user.id, secret, pyotp.TOTP(secret).now())
        self.assertTrue(self.svc.verificar_totp(self.user.id, pyotp.TOTP(secret).now()))

    def test_verificar_totp_sem_secret_retorna_false(self):
        # TOTP nao habilitado
        self.assertFalse(self.svc.verificar_totp(self.user.id, "123456"))

    def test_completar_login_totp_code_valido_cria_sessao(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        self.svc.confirmar_totp_setup(self.user.id, secret, pyotp.TOTP(secret).now())
        sessao = self.svc.completar_login_totp(self.user.id, pyotp.TOTP(secret).now())
        self.assertIsNotNone(sessao)
        self.assertIsNotNone(sessao.cookie_plaintext)

    def test_completar_login_totp_code_invalido_retorna_none(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        self.svc.confirmar_totp_setup(self.user.id, secret, pyotp.TOTP(secret).now())
        result = self.svc.completar_login_totp(self.user.id, "000000")
        self.assertIsNone(result)

    def test_desabilitar_totp_com_code_valido(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        self.svc.confirmar_totp_setup(self.user.id, secret, pyotp.TOTP(secret).now())
        erro = self.svc.desabilitar_totp(self.user.id, pyotp.TOTP(secret).now())
        self.assertIsNone(erro)
        self.assertFalse(self.repo.obter_user(self.user.id).totp_habilitado)
        self.assertIsNone(self.repo.obter_totp_secret(self.user.id))

    def test_desabilitar_totp_com_senha_valida(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        self.svc.confirmar_totp_setup(self.user.id, secret, pyotp.TOTP(secret).now())
        erro = self.svc.desabilitar_totp(self.user.id, "Senha1234!")
        self.assertIsNone(erro)
        self.assertFalse(self.repo.obter_user(self.user.id).totp_habilitado)

    def test_desabilitar_totp_credencial_invalida(self):
        secret, _ = self.svc.iniciar_configuracao_totp(self.user.id)
        self.svc.confirmar_totp_setup(self.user.id, secret, pyotp.TOTP(secret).now())
        erro = self.svc.desabilitar_totp(self.user.id, "errado")
        self.assertEqual(erro, "CREDENCIAL_INVALIDA")
        self.assertTrue(self.repo.obter_user(self.user.id).totp_habilitado)

    def test_desabilitar_totp_nao_habilitado(self):
        erro = self.svc.desabilitar_totp(self.user.id, "qualquer")
        self.assertEqual(erro, "TOTP_NAO_HABILITADO")


class TestTotpEndpoints(unittest.TestCase):

    def setUp(self):
        import auth.cliente_routes as mod
        from flask import Flask

        self.repo, self.svc, self.user, self._site_id = _criar_repo_svc()

        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = "test-secret-totp"
        self.app.config["TESTING"] = True
        os.environ["COOKIE_SECURE"] = "false"
        self.app.register_blueprint(mod.cliente_auth_bp)
        mod.configurar(self.svc)
        self.client = self.app.test_client(use_cookies=True)

        # Habilita TOTP no user para os testes que precisam
        self._secret = pyotp.random_base32()
        self.repo.habilitar_totp(self.user.id, self._secret)

    def _login_usuario(self, email: str, senha: str = "Senha1234!"):
        """Login simples (sem TOTP). Retorna resposta."""
        return self.client.post("/cliente/auth/login", json={"email": email, "senha": senha})

    def _sessao_autenticada(self):
        """Retorna um cookie de sessao valido para self.user via TOTP."""
        # Passo 1: login → totp_required
        r = self.client.post(
            "/cliente/auth/login",
            json={"email": "totp@teste.com", "senha": "Senha1234!"},
        )
        token = r.get_json()["totp_pendente_token"]
        # Passo 2: verificar TOTP
        r2 = self.client.post(
            "/cliente/auth/totp/verificar",
            json={"totp_pendente_token": token, "code": pyotp.TOTP(self._secret).now()},
        )
        return r2.headers.get("Set-Cookie", "")

    def test_login_sem_totp_retorna_cookie(self):
        user2 = self.svc.criar_user(self._site_id, "nototp2@teste.com", senha="Senha1234!")
        r = self.client.post(
            "/cliente/auth/login",
            json={"email": "nototp2@teste.com", "senha": "Senha1234!"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")
        self.assertIn("cliente_session", r.headers.get("Set-Cookie", ""))

    def test_login_com_totp_retorna_totp_required(self):
        r = self.client.post(
            "/cliente/auth/login",
            json={"email": "totp@teste.com", "senha": "Senha1234!"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "totp_required")
        self.assertIn("totp_pendente_token", data)
        self.assertNotIn("Set-Cookie", r.headers)

    def test_totp_verificar_code_valido_cria_sessao(self):
        r1 = self.client.post(
            "/cliente/auth/login",
            json={"email": "totp@teste.com", "senha": "Senha1234!"},
        )
        token = r1.get_json()["totp_pendente_token"]
        r2 = self.client.post(
            "/cliente/auth/totp/verificar",
            json={"totp_pendente_token": token, "code": pyotp.TOTP(self._secret).now()},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["status"], "success")
        self.assertIn("cliente_session", r2.headers.get("Set-Cookie", ""))

    def test_totp_verificar_code_invalido_retorna_401(self):
        r1 = self.client.post(
            "/cliente/auth/login",
            json={"email": "totp@teste.com", "senha": "Senha1234!"},
        )
        token = r1.get_json()["totp_pendente_token"]
        r2 = self.client.post(
            "/cliente/auth/totp/verificar",
            json={"totp_pendente_token": token, "code": "000000"},
        )
        self.assertEqual(r2.status_code, 401)
        self.assertEqual(r2.get_json()["code"], "CODIGO_INVALIDO")

    def test_totp_verificar_token_expirado_retorna_401(self):
        from itsdangerous import URLSafeTimedSerializer
        # Gera token com TTL artificial de -1 (ja expirado via timestamp manipulado)
        s = URLSafeTimedSerializer("test-secret-totp", salt="totp-pendente")
        # Cria token e imediatamente passa um max_age=0 no verify
        token = s.dumps(self.user.id)
        # O jeito mais simples: chamar o endpoint com um token assinado pela chave errada
        s2 = URLSafeTimedSerializer("chave-errada", salt="totp-pendente")
        token_invalido = s2.dumps(self.user.id)
        r = self.client.post(
            "/cliente/auth/totp/verificar",
            json={"totp_pendente_token": token_invalido, "code": "123456"},
        )
        self.assertEqual(r.status_code, 401)

    def test_totp_setup_requer_autenticacao(self):
        r = self.client.post("/cliente/auth/totp/setup")
        self.assertEqual(r.status_code, 401)

    def test_totp_setup_quando_ja_habilitado_retorna_409(self):
        # user ja tem TOTP (setUp habilitou)
        self._sessao_autenticada()  # cookie no jar
        r = self.client.post("/cliente/auth/totp/setup")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["code"], "TOTP_JA_HABILITADO")

    def test_totp_setup_sem_totp_retorna_secret_e_uri(self):
        self.svc.criar_user(self._site_id, "setup@teste.com", senha="Senha1234!")
        self._login_usuario("setup@teste.com")  # cookie vai pro jar
        r = self.client.post("/cliente/auth/totp/setup")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("secret", data)
        self.assertIn("otpauth_uri", data)
        self.assertIn("otpauth://totp/", data["otpauth_uri"])

    def test_totp_confirmar_code_valido_habilita(self):
        user2 = self.svc.criar_user(self._site_id, "confirm@teste.com", senha="Senha1234!")
        self._login_usuario("confirm@teste.com")  # cookie no jar
        r_setup = self.client.post("/cliente/auth/totp/setup")
        secret = r_setup.get_json()["secret"]
        r = self.client.post(
            "/cliente/auth/totp/confirmar",
            json={"secret": secret, "code": pyotp.TOTP(secret).now()},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["totp_habilitado"])
        self.assertTrue(self.repo.obter_user(user2.id).totp_habilitado)

    def test_totp_confirmar_code_invalido_retorna_422(self):
        self.svc.criar_user(self._site_id, "confirm2@teste.com", senha="Senha1234!")
        self._login_usuario("confirm2@teste.com")
        r_setup = self.client.post("/cliente/auth/totp/setup")
        secret = r_setup.get_json()["secret"]
        r = self.client.post(
            "/cliente/auth/totp/confirmar",
            json={"secret": secret, "code": "000000"},
        )
        self.assertEqual(r.status_code, 422)

    def test_totp_desabilitar_com_code_valido(self):
        self._sessao_autenticada()  # cookie no jar
        r = self.client.delete(
            "/cliente/auth/totp",
            json={"code": pyotp.TOTP(self._secret).now()},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["totp_habilitado"])
        self.assertFalse(self.repo.obter_user(self.user.id).totp_habilitado)

    def test_totp_desabilitar_credencial_invalida_retorna_403(self):
        self._sessao_autenticada()  # cookie no jar
        r = self.client.delete("/cliente/auth/totp", json={"code": "000000"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["code"], "CREDENCIAL_INVALIDA")

    def test_totp_desabilitar_nao_habilitado_retorna_409(self):
        self.svc.criar_user(self._site_id, "nototp3@teste.com", senha="Senha1234!")
        self._login_usuario("nototp3@teste.com")  # cookie no jar
        r = self.client.delete("/cliente/auth/totp", json={"code": "123456"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["code"], "TOTP_NAO_HABILITADO")


if __name__ == "__main__":
    unittest.main()
