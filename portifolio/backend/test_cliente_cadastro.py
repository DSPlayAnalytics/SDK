"""Testes do endpoint POST /cliente/auth/cadastro.

Escopo (XP/TDD — cresce um teste por vez):
  - happy path: cria site + admin user + auto-login, retorna 201 com cookie
  - email duplicado -> 409
  - slug duplicado -> 409
  - payload invalido -> 400
  - bucket_name segue convencao `cliente_<slug>`
  - papel do user criado e `admin`

Os campos obrigatorios sao {email, senha, nome_site, slug}. O endpoint
publica um cookie cliente_session imediatamente para o landing redirecionar
o user direto pra /cliente/metricas apos o cadastro.
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
from auth.sessao_service import SessaoService
from auth.tenants_repo import SqliteTenantsRepo


def _criar_app_cadastro(tenants, users, svc):
    import os as _os
    from flask import Flask
    from auth import cliente_routes as mod

    app = Flask(__name__)
    mod._svc_instance = svc
    mod._tenants_repo = tenants
    mod._clientes_users_repo = users
    _os.environ["COOKIE_SECURE"] = "false"
    app.register_blueprint(mod.cliente_auth_bp)
    app.testing = True
    return app


class CadastroEndpointTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(self._tmp.name) / "tenants.db")
        self.tenants = SqliteTenantsRepo(db_path)
        self.users = SqliteClientesUsersRepo(db_path)
        self.svc = SessaoService(self.users, sessao_ttl_segundos=3600)
        self.app = _criar_app_cadastro(self.tenants, self.users, self.svc)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self, **overrides):
        base = {
            "email": "dan@acme.com",
            "senha": "secret-123",
            "nome_site": "ACME Corp",
            "slug": "acme",
        }
        base.update(overrides)
        return base

    def test_cadastro_happy_path_retorna_201_com_cookie(self):
        r = self.client.post("/cliente/auth/cadastro", json=self._payload())
        self.assertEqual(r.status_code, 201)
        self.assertIn("cliente_session", r.headers.get("Set-Cookie", ""))
        body = r.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["user"]["email"], "dan@acme.com")
        self.assertEqual(body["user"]["papel"], "admin")
        self.assertTrue(body["user"]["site_id"])

    def test_cadastro_cria_site_com_bucket_padrao_cliente_slug(self):
        r = self.client.post("/cliente/auth/cadastro", json=self._payload())
        site = self.tenants.obter_site_por_slug("acme")
        self.assertIsNotNone(site)
        self.assertEqual(site.nome, "ACME Corp")
        self.assertEqual(site.bucket_name, "cliente_acme")
        self.assertEqual(site.plano, "free")

    def test_cadastro_email_duplicado_retorna_409(self):
        self.client.post("/cliente/auth/cadastro", json=self._payload())
        r = self.client.post(
            "/cliente/auth/cadastro",
            json=self._payload(slug="outro", nome_site="Outro"),
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["code"], "EMAIL_JA_CADASTRADO")

    def test_cadastro_slug_duplicado_retorna_409(self):
        self.client.post("/cliente/auth/cadastro", json=self._payload())
        r = self.client.post(
            "/cliente/auth/cadastro",
            json=self._payload(email="outro@x.com"),
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["code"], "SLUG_JA_CADASTRADO")

    def test_cadastro_payload_incompleto_retorna_400(self):
        for falta in ("email", "senha", "nome_site", "slug"):
            payload = self._payload()
            payload.pop(falta)
            r = self.client.post("/cliente/auth/cadastro", json=payload)
            self.assertEqual(r.status_code, 400, f"campo ausente: {falta}")

    def test_cadastro_slug_invalido_retorna_400(self):
        for slug_ruim in ("Acme Corp", "acme!", "AC", "", "a" * 100):
            r = self.client.post(
                "/cliente/auth/cadastro",
                json=self._payload(slug=slug_ruim),
            )
            self.assertEqual(r.status_code, 400, f"slug invalido aceito: {slug_ruim!r}")

    def test_cadastro_email_invalido_retorna_400(self):
        for email_ruim in ("nao-tem-arroba", "x@", "@y.com", ""):
            r = self.client.post(
                "/cliente/auth/cadastro",
                json=self._payload(email=email_ruim),
            )
            self.assertEqual(r.status_code, 400, f"email invalido aceito: {email_ruim!r}")

    def test_cadastro_senha_curta_retorna_400(self):
        r = self.client.post(
            "/cliente/auth/cadastro",
            json=self._payload(senha="abc"),
        )
        self.assertEqual(r.status_code, 400)


class CadastroTriggerProvisionamentoTests(unittest.TestCase):
    """P0 #2: cadastro bem-sucedido dispara provisionamento idempotente
    (bucket Influx + org Grafana + datasource + dashboards).

    Best-effort: se provisionamento falhar, cadastro ainda retorna 201
    (admin reconcilia depois). Logs em security_logger registram resultado.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(self._tmp.name) / "tenants.db")
        self.tenants = SqliteTenantsRepo(db_path)
        self.users = SqliteClientesUsersRepo(db_path)
        self.svc = SessaoService(self.users, sessao_ttl_segundos=3600)

        # Patch do hook de provisionamento — captura chamadas
        from auth import cliente_routes as mod
        self._mod = mod
        self._provisionar_original = getattr(mod, "_provisionar_pos_cadastro", None)
        self.calls: list[dict] = []
        self.should_raise: Exception | None = None

        def _fake(**kwargs):
            self.calls.append(kwargs)
            if self.should_raise is not None:
                raise self.should_raise

        mod._provisionar_pos_cadastro = _fake

        self.app = _criar_app_cadastro(self.tenants, self.users, self.svc)
        self.client = self.app.test_client()

    def tearDown(self):
        if self._provisionar_original is not None:
            self._mod._provisionar_pos_cadastro = self._provisionar_original
        else:
            try:
                delattr(self._mod, "_provisionar_pos_cadastro")
            except AttributeError:
                pass
        self._tmp.cleanup()

    def _payload(self, **overrides):
        base = {
            "email": "dan@acme.com", "senha": "secret-123",
            "nome_site": "ACME Corp", "slug": "acme",
        }
        base.update(overrides)
        return base

    def test_cadastro_ok_dispara_provisionar(self):
        r = self.client.post("/cliente/auth/cadastro", json=self._payload())
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(self.calls), 1)
        kwargs = self.calls[0]
        self.assertEqual(kwargs["slug"], "acme")
        self.assertEqual(kwargs["nome"], "ACME Corp")
        self.assertEqual(kwargs["plano"], "free")
        # ambiente vem do env (default production no handler)
        self.assertIn("ambiente", kwargs)

    def test_cadastro_ok_passa_site_id_pro_provisionar(self):
        r = self.client.post("/cliente/auth/cadastro", json=self._payload())
        body = r.get_json()
        self.assertEqual(self.calls[0]["site_id"], body["user"]["site_id"])

    def test_cadastro_continua_201_mesmo_se_provisionar_falhar(self):
        self.should_raise = RuntimeError("influx fora do ar")
        r = self.client.post("/cliente/auth/cadastro", json=self._payload())
        self.assertEqual(r.status_code, 201, "cadastro NAO pode falhar por causa de provisionamento")
        self.assertEqual(len(self.calls), 1)

    def test_cadastro_com_payload_invalido_NAO_dispara_provisionar(self):
        r = self.client.post("/cliente/auth/cadastro", json=self._payload(email="x@"))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(self.calls), 0, "provisionar so deve disparar apos cadastro 201")

    def test_cadastro_com_email_duplicado_NAO_dispara_provisionar(self):
        self.client.post("/cliente/auth/cadastro", json=self._payload())
        # primeira chamada disparou
        self.assertEqual(len(self.calls), 1)
        # tentativa duplicada nao dispara
        r2 = self.client.post(
            "/cliente/auth/cadastro",
            json=self._payload(slug="outro"),
        )
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(len(self.calls), 1, "duplicado nao deve disparar de novo")


if __name__ == "__main__":
    unittest.main()
