"""TDD do endpoint GET /cliente/configuracoes.

Retorna user + site + publishable_keys ativas + quota + consumo do dia, escopado
ao site do user via cookie cliente_session. Tudo derivado de site_id do cookie —
nunca recebe site_id por path/query (anti-IDOR).

Schema da resposta:
{
  "user":  {"id", "email", "papel"},
  "site":  {"id", "slug", "nome", "ambiente", "plano", "bucket_name"},
  "publishable_keys": [{"key_id", "valor", "nome", "ambiente", "criado_em"}],
  "quota": {"eventos_por_minuto", "eventos_por_dia",
            "emissoes_jwt_por_minuto", "retencao_dias"},
  "consumo": {"eventos_hoje": int}
}

Auth: cookie cliente_session valido. Sem cookie -> 401.
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


def _preparar_db(tmpdir: Path):
    db_path = str(tmpdir / "tenants.db")
    tenants = SqliteTenantsRepo(db_path)
    users = SqliteClientesUsersRepo(db_path)
    site = tenants.criar_site(
        slug="acme", nome="ACME Corp",
        ambiente="development", dominios=["https://acme.test"],
        plano="medio",
    )
    return tenants, users, site.id


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


class ClienteConfiguracoesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tenants, self.users, self.site_id = _preparar_db(Path(self._tmp.name))
        self.svc = SessaoService(self.users, sessao_ttl_segundos=3600)
        self.svc.criar_user(self.site_id, "dan@acme.com", senha="secret-123", papel="admin")

        # Publishable key + quota + consumo do dia atual
        self.tenants.criar_publishable_key(self.site_id, "production", nome="prod-principal")
        self.tenants.atualizar_quota(self.site_id, eventos_por_dia=1_000_000,
                                     eventos_por_minuto=5_000, retencao_dias=90)
        self.tenants.incrementar_consumo(self.site_id, eventos=42)

        self.app = _criar_app(self.tenants, self.users, self.svc)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def _login(self):
        r = self.client.post("/cliente/auth/login",
                             json={"email": "dan@acme.com", "senha": "secret-123"})
        self.assertEqual(r.status_code, 200)

    def test_sem_cookie_retorna_401(self):
        r = self.client.get("/cliente/auth/configuracoes")
        self.assertEqual(r.status_code, 401)

    def test_com_cookie_retorna_user_site_keys_quota_consumo(self):
        self._login()
        r = self.client.get("/cliente/auth/configuracoes")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()

        self.assertEqual(body["user"]["email"], "dan@acme.com")
        self.assertEqual(body["user"]["papel"], "admin")
        self.assertIn("id", body["user"])

        self.assertEqual(body["site"]["slug"], "acme")
        self.assertEqual(body["site"]["nome"], "ACME Corp")
        self.assertEqual(body["site"]["plano"], "medio")
        self.assertEqual(body["site"]["ambiente"], "development")

        self.assertEqual(len(body["publishable_keys"]), 1)
        pk = body["publishable_keys"][0]
        self.assertTrue(pk["valor"].startswith("pk_production_"))
        self.assertEqual(pk["nome"], "prod-principal")
        self.assertIn("key_id", pk)
        # Tem que ter ambiente derivado do prefix
        self.assertEqual(pk["ambiente"], "production")

        self.assertEqual(body["quota"]["eventos_por_dia"], 1_000_000)
        self.assertEqual(body["quota"]["retencao_dias"], 90)

        self.assertEqual(body["consumo"]["eventos_hoje"], 42)

        # Cardinalidade: tracker zerado pra site novo, limite vem do plano
        # 'medio' (50_000 — ver ingestao/cardinalidade.py:LIMITE_POR_PLANO).
        self.assertIn("cardinalidade", body)
        self.assertEqual(body["cardinalidade"]["atual"], 0)
        self.assertEqual(body["cardinalidade"]["limite"], 50_000)

    def test_publishable_keys_revogadas_nao_aparecem(self):
        # criar 2a key e revogar a 1a
        keys_antes = self.tenants.listar_publishable_keys(self.site_id)
        self.assertEqual(len(keys_antes), 1)
        self.tenants.revogar_publishable_key(keys_antes[0].key_id)
        self.tenants.criar_publishable_key(self.site_id, "production", nome="rotacionada")

        self._login()
        r = self.client.get("/cliente/auth/configuracoes")
        body = r.get_json()
        self.assertEqual(len(body["publishable_keys"]), 1)
        self.assertEqual(body["publishable_keys"][0]["nome"], "rotacionada")

    def test_cardinalidade_reflete_uso_real_do_tracker(self):
        # Injeta tracker e popula valores pro site
        from ingestao import cardinalidade as cardmod
        cardmod.resetar_tracker()
        tracker = cardmod.obter_tracker()

        # Adiciona 100 valores em 2 tags = 100 (page_type tem 60 distintos,
        # device_type tem 40 distintos)
        pares = [("page_type", f"/p{i}") for i in range(60)]
        pares += [("device_type", f"d{i}") for i in range(40)]
        tracker.verificar_e_registrar(self.site_id, pares, limite=50_000)

        self._login()
        r = self.client.get("/cliente/auth/configuracoes")
        body = r.get_json()

        self.assertEqual(body["cardinalidade"]["atual"], 100)
        self.assertEqual(body["cardinalidade"]["limite"], 50_000)

        # cleanup pra nao poluir outros tests
        cardmod.resetar_tracker()

    def test_isolamento_site_outro_user_nao_vaza(self):
        # cria 2o site com sua propria pk + 2o user
        site2 = self.tenants.criar_site(
            slug="outra-empresa", nome="Outra",
            ambiente="production", dominios=["https://outra.test"], plano="grande",
        )
        self.tenants.criar_publishable_key(site2.id, "production", nome="outro-segredo")
        self.svc.criar_user(site2.id, "user2@outra.com", senha="secret-456", papel="admin")

        # login com user1 nao vaza nada do site2
        self._login()
        r = self.client.get("/cliente/auth/configuracoes")
        body = r.get_json()
        self.assertEqual(body["site"]["slug"], "acme")
        keys = [pk["valor"] for pk in body["publishable_keys"]]
        for v in keys:
            self.assertNotIn("outro-segredo", v)
        # E o nome 'outro-segredo' nao aparece em parte nenhuma da resposta
        import json as _json
        bruto = _json.dumps(body)
        self.assertNotIn("outro-segredo", bruto)
        self.assertNotIn("outra-empresa", bruto)

    def test_quota_default_quando_site_nao_tem_quota_configurada(self):
        # outro site sem chamar criar_quota — endpoint deve retornar defaults
        site3 = self.tenants.criar_site(
            slug="sem-quota", nome="Sem Quota",
            ambiente="development", dominios=[], plano="free",
        )
        self.svc.criar_user(site3.id, "u3@x.com", senha="secret-789", papel="admin")

        self.client.post("/cliente/auth/login",
                         json={"email": "u3@x.com", "senha": "secret-789"})
        r = self.client.get("/cliente/auth/configuracoes")
        body = r.get_json()
        # Sem quota explicita, ainda retorna estrutura completa (defaults Postgres
        # ja inseridos pelo trigger ou repo retorna None e endpoint preenche)
        self.assertIn("quota", body)
        self.assertGreater(body["quota"]["retencao_dias"], 0)


class BillingPlanosIntegracaoTests(unittest.TestCase):
    """Integracao: GET /billing/planos acessivel sem auth e retorna lista de planos."""

    def setUp(self):
        from flask import Flask
        from billing.routes import billing_routes_bp

        app = Flask(__name__)
        app.register_blueprint(billing_routes_bp)
        app.testing = True
        self.client = app.test_client()

    def test_billing_planos_retorna_200_com_lista_de_planos(self):
        r = self.client.get("/billing/planos")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("planos", body)
        # PLANO_DEFAULTS expoe 2 planos (free, pro). Os legados
        # pequeno/medio/grande foram consolidados em pro durante o
        # refactor da Stripe billing.
        self.assertEqual(len(body["planos"]), 2)
        ids = [p["id"] for p in body["planos"]]
        self.assertEqual(ids, ["free", "pro"])


if __name__ == "__main__":
    unittest.main()
