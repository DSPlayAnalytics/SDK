"""Testes de autenticação obrigatória nos endpoints `/analytics/*`.

Antes desta correção, esses endpoints eram públicos: qualquer um passava
`app_id=X` e lia agregados de qualquer site. Vazamento passivo do isolamento
multi-tenant — bucket-per-cliente já isolava na ingest, mas a consulta
estava aberta.

Comportamento esperado:
  1. Sem cookie `cliente_session` → 401
  2. Com cookie inválido → 401
  3. Com cookie válido → 200, e a query no InfluxDB usa o bucket
     `cliente_<slug>` do site_id do cookie (NÃO o bucket default).
  4. Param `app_id` da querystring é ignorado se conflitar com o site
     do cookie — cliente só lê do próprio site.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Sobrescrever env ANTES de importar app — pra usar SQLite e threading
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ["TENANTS_DATABASE_URL"] = f"sqlite:///{_TMP_DB.name}"
os.environ["SOCKETIO_ASYNC_MODE"] = "threading"
os.environ["COOKIE_SECURE"] = "false"

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app as app_module
from auth.clientes_users_repo import SqliteClientesUsersRepo
from auth.sessao_service import SessaoService
from auth.tenants_repo import SqliteTenantsRepo


class _CapturadorInfluxDB:
    """Mock que captura kwargs das queries pra verificar bucket forçado."""

    def __init__(self):
        self.metricas_calls: list[dict] = []
        self.vitals_calls: list[dict] = []
        self.customs_calls: list[dict] = []

    def query_metricas_agregadas(self, **kwargs):
        self.metricas_calls.append(kwargs)
        return []

    def query_web_vitals(self, **kwargs):
        self.vitals_calls.append(kwargs)
        return []

    def query_custom_events(self, **kwargs):
        self.customs_calls.append(kwargs)
        return []

    def is_healthy(self):
        return True


def _criar_site_e_cookie(slug: str = "acme") -> tuple[str, str, str]:
    """Cria site + user + sessão; retorna (site_id, slug, cookie_plaintext).

    Usa o DB SQLite ja apontado em app.config (mesmo que o app importou).
    Hot-swap do svc + tenants_repo do cliente_routes pra apontar pros mesmos.
    """
    db_path = app_module.app.config["TENANTS_DATABASE_URL"][len("sqlite:///"):]
    tenants = SqliteTenantsRepo(db_path)
    users = SqliteClientesUsersRepo(db_path)
    site = tenants.criar_site(
        slug=slug, nome=f"Site {slug}",
        ambiente="development", dominios=[f"https://{slug}.test"],
        bucket_name=f"cliente_{slug}",
    )
    svc = SessaoService(users)
    user = svc.criar_user(site.id, f"dan@{slug}.com", senha="secret-123", papel="admin")
    sessao = svc.criar_sessao(user.id)
    from auth import cliente_routes as mod
    mod._svc_instance = svc
    mod._tenants_repo = tenants
    return site.id, site.slug, sessao.cookie_plaintext


class AnalyticsAuthTests(unittest.TestCase):
    _seq = 0

    def setUp(self):
        self.client = app_module.app.test_client()
        self._influx_original = app_module.influxdb_service
        self.captor = _CapturadorInfluxDB()
        app_module.influxdb_service = self.captor
        # slug unico por test pra nao colidir uniqueness no SQLite compartilhado
        AnalyticsAuthTests._seq += 1
        self.slug = f"acme{AnalyticsAuthTests._seq}"

    def tearDown(self):
        app_module.influxdb_service = self._influx_original

    # ============== /analytics/metricas ==============

    def test_metricas_sem_cookie_retorna_401(self):
        r = self.client.get('/analytics/metricas')
        self.assertEqual(r.status_code, 401)

    def test_metricas_com_cookie_invalido_retorna_401(self):
        self.client.set_cookie('cliente_session', 'token-invalido', domain='localhost')
        r = self.client.get('/analytics/metricas')
        self.assertEqual(r.status_code, 401)

    def test_metricas_com_cookie_valido_usa_bucket_do_site(self):
        site_id, slug, cookie = _criar_site_e_cookie(self.slug)
        self.client.set_cookie('cliente_session', cookie, domain='localhost')
        r = self.client.get('/analytics/metricas')
        self.assertEqual(r.status_code, 200)
        # Deve ter chamado query com bucket forçado
        self.assertEqual(len(self.captor.metricas_calls), 1)
        kwargs = self.captor.metricas_calls[0]
        self.assertEqual(kwargs.get('bucket'), f'cliente_{slug}')

    def test_metricas_app_id_querystring_ignorado_se_conflitar(self):
        """Cliente passa app_id arbitrário → query ainda usa bucket do site dele."""
        site_id, slug, cookie = _criar_site_e_cookie(self.slug)
        self.client.set_cookie('cliente_session', cookie, domain='localhost')
        r = self.client.get('/analytics/metricas?app_id=outro-site-malicioso')
        self.assertEqual(r.status_code, 200)
        kwargs = self.captor.metricas_calls[0]
        # bucket SEMPRE é o do site do cookie, independente do app_id passado
        self.assertEqual(kwargs.get('bucket'), f'cliente_{slug}')

    # ============== /analytics/web-vitals ==============

    def test_web_vitals_sem_cookie_retorna_401(self):
        r = self.client.get('/analytics/web-vitals')
        self.assertEqual(r.status_code, 401)

    def test_web_vitals_com_cookie_valido_usa_bucket_do_site(self):
        site_id, slug, cookie = _criar_site_e_cookie(self.slug)
        self.client.set_cookie('cliente_session', cookie, domain='localhost')
        r = self.client.get('/analytics/web-vitals')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.captor.vitals_calls), 1)
        self.assertEqual(self.captor.vitals_calls[0].get('bucket'), f'cliente_{slug}')

    # ============== /analytics/custom-events ==============

    def test_custom_events_sem_cookie_retorna_401(self):
        r = self.client.get('/analytics/custom-events')
        self.assertEqual(r.status_code, 401)

    def test_custom_events_com_cookie_valido_usa_bucket_do_site(self):
        site_id, slug, cookie = _criar_site_e_cookie(self.slug)
        self.client.set_cookie('cliente_session', cookie, domain='localhost')
        r = self.client.get('/analytics/custom-events?nome=checkout_iniciado')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.captor.customs_calls), 1)
        self.assertEqual(self.captor.customs_calls[0].get('bucket'), f'cliente_{slug}')

    def test_corpo_da_resposta_inclui_site_id_em_filtros(self):
        """Resposta documenta qual site foi consultado (anti-confusão)."""
        site_id, slug, cookie = _criar_site_e_cookie(self.slug)
        self.client.set_cookie('cliente_session', cookie, domain='localhost')
        r = self.client.get('/analytics/metricas')
        body = r.get_json()
        self.assertEqual(body['filtros'].get('site_id'), site_id)


if __name__ == "__main__":
    unittest.main()
