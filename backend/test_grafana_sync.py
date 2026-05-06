"""Testes do GrafanaSyncService — sec 13 do dashboard-cliente.md, sprint 2 item 2.

Cobre:
  - Cache TTL: chamada repetida nao bate na API.
  - Idempotencia: org ja existente, user ja membro -> sem erro.
  - Race do auth.proxy: user ainda nao existe em Grafana -> retorna False
    sem cachear (proximo /gate tenta de novo).
  - Failures (Grafana down) NAO derrubam — retornam False, logam, nao cacheiam.
  - garantir_membership chama add_org_user + set_user_current_org.
  - invalidar() / limpar() funcionam.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.grafana_sync import GrafanaSyncService  # noqa: E402


def _client_mock():
    """Mock de GrafanaClient com defaults razoaveis."""
    m = MagicMock()
    m.get_org_by_name.return_value = {"id": 42, "name": "cliente_acme"}
    m.get_user_by_login.return_value = {"id": 7, "login": "site-uuid"}
    m.add_org_user.return_value = True  # adicionado pela primeira vez
    m.set_user_current_org.return_value = None
    m.remove_org_user.return_value = True  # removido do Main Org
    return m


class GarantirMembershipTests(unittest.TestCase):
    def test_sucesso_chama_add_e_set_current(self):
        client = _client_mock()
        svc = GrafanaSyncService(client, main_org_id=1)
        ok = svc.garantir_membership("site-uuid", "cliente_acme")
        self.assertTrue(ok)
        client.get_org_by_name.assert_called_once_with("cliente_acme")
        client.get_user_by_login.assert_called_once_with("site-uuid")
        client.add_org_user.assert_called_once_with(42, login="site-uuid", role="Viewer")
        client.set_user_current_org.assert_called_once_with(7, 42)
        # Passo 5: remove do Main Org (id=1) para isolar o tenant.
        client.remove_org_user.assert_called_once_with(1, 7)

    def test_remove_do_main_org_nao_acontece_quando_target_e_main_org(self):
        """Se target_org_id == main_org_id, nao deve chamar remove (evita auto-expulsao)."""
        client = _client_mock()
        client.get_org_by_name.return_value = {"id": 1, "name": "Main Org"}
        svc = GrafanaSyncService(client, main_org_id=1)
        ok = svc.garantir_membership("site-uuid", "Main Org")
        self.assertTrue(ok)
        client.remove_org_user.assert_not_called()

    def test_cache_hit_evita_chamadas_grafana(self):
        client = _client_mock()
        svc = GrafanaSyncService(client, ttl_seconds=3600)
        self.assertTrue(svc.garantir_membership("site-uuid", "cliente_acme"))
        # Limpa contadores e chama de novo: NAO deve bater na API.
        client.reset_mock()
        self.assertTrue(svc.garantir_membership("site-uuid", "cliente_acme"))
        client.get_org_by_name.assert_not_called()
        client.get_user_by_login.assert_not_called()
        client.add_org_user.assert_not_called()

    def test_ttl_expirado_dispara_resync(self):
        client = _client_mock()
        svc = GrafanaSyncService(client, ttl_seconds=0)  # expira imediatamente
        svc.garantir_membership("site-uuid", "cliente_acme")
        client.reset_mock()
        # Pequena pausa pra sair da janela ttl=0 (monotonic granularity).
        time.sleep(0.01)
        client.get_org_by_name.return_value = {"id": 42}
        client.get_user_by_login.return_value = {"id": 7}
        svc.garantir_membership("site-uuid", "cliente_acme")
        client.get_org_by_name.assert_called_once()

    def test_org_inexistente_retorna_false_sem_cachear(self):
        client = _client_mock()
        client.get_org_by_name.return_value = None
        svc = GrafanaSyncService(client)
        ok = svc.garantir_membership("site-uuid", "cliente_acme")
        self.assertFalse(ok)
        # Nao cacheia falha -> chamada seguinte tenta de novo.
        client.reset_mock()
        client.get_org_by_name.return_value = None
        svc.garantir_membership("site-uuid", "cliente_acme")
        client.get_org_by_name.assert_called_once()

    def test_user_pendente_retorna_false_sem_cachear(self):
        """Race do auth.proxy: user ainda nao foi criado pelo primeiro hit."""
        client = _client_mock()
        client.get_user_by_login.return_value = None
        svc = GrafanaSyncService(client)
        ok = svc.garantir_membership("site-uuid", "cliente_acme")
        self.assertFalse(ok)
        # add_org_user e set_user_current_org NAO devem ter sido chamados.
        client.add_org_user.assert_not_called()
        client.set_user_current_org.assert_not_called()
        # Proximo retry deve voltar ao Grafana.
        client.reset_mock()
        client.get_org_by_name.return_value = {"id": 42}
        client.get_user_by_login.return_value = None
        svc.garantir_membership("site-uuid", "cliente_acme")
        client.get_user_by_login.assert_called_once()

    def test_409_em_add_org_user_ja_eh_membro(self):
        """add_org_user retorna False se ja era membro — fluxo continua."""
        client = _client_mock()
        client.add_org_user.return_value = False
        svc = GrafanaSyncService(client)
        ok = svc.garantir_membership("site-uuid", "cliente_acme")
        self.assertTrue(ok)
        client.set_user_current_org.assert_called_once()

    def test_excecao_no_client_nao_propaga_e_nao_cacheia(self):
        client = _client_mock()
        client.add_org_user.side_effect = RuntimeError("grafana 500")
        svc = GrafanaSyncService(client)
        ok = svc.garantir_membership("site-uuid", "cliente_acme")
        self.assertFalse(ok)
        # Cache nao deve guardar falha -> proxima tentativa retenta.
        client.reset_mock()
        client.add_org_user.side_effect = None
        client.add_org_user.return_value = True
        ok = svc.garantir_membership("site-uuid", "cliente_acme")
        self.assertTrue(ok)

    def test_login_ou_org_vazio_retorna_false(self):
        svc = GrafanaSyncService(_client_mock())
        self.assertFalse(svc.garantir_membership("", "cliente_acme"))
        self.assertFalse(svc.garantir_membership("site", ""))
        self.assertFalse(svc.garantir_membership(None, None))  # type: ignore[arg-type]

    def test_invalidar_remove_apenas_chave_alvo(self):
        client = _client_mock()
        svc = GrafanaSyncService(client)
        svc.garantir_membership("site-A", "cliente_a")
        svc.garantir_membership("site-B", "cliente_b")
        client.reset_mock()
        svc.invalidar("site-A", "cliente_a")
        # site-A precisa resync; site-B continua cacheado.
        svc.garantir_membership("site-A", "cliente_a")
        client.get_org_by_name.assert_called_once_with("cliente_a")
        client.reset_mock()
        svc.garantir_membership("site-B", "cliente_b")
        client.get_org_by_name.assert_not_called()


class CriarServicoSeConfiguradoTests(unittest.TestCase):
    def setUp(self):
        # Salva e limpa env relevantes
        self._envs = {}
        for k in ("GRAFANA_URL", "GRAFANA_ADMIN_USER", "GRAFANA_ADMIN_PASSWORD",
                  "GRAFANA_SYNC_TTL_SECONDS"):
            self._envs[k] = os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._envs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_sem_envs_retorna_none(self):
        from auth.grafana_sync import criar_servico_se_configurado
        self.assertIsNone(criar_servico_se_configurado())

    def test_com_envs_retorna_servico(self):
        os.environ["GRAFANA_URL"] = "http://grafana:3000"
        os.environ["GRAFANA_ADMIN_USER"] = "admin"
        os.environ["GRAFANA_ADMIN_PASSWORD"] = "admin"
        os.environ["GRAFANA_SYNC_TTL_SECONDS"] = "120"
        from auth.grafana_sync import criar_servico_se_configurado
        svc = criar_servico_se_configurado()
        self.assertIsNotNone(svc)
        self.assertEqual(svc._ttl, 120)  # noqa: SLF001


class GateIntegracaoSyncTests(unittest.TestCase):
    """`/gate` chama grafana_sync.garantir_membership best-effort."""

    def setUp(self):
        import tempfile
        from auth.clientes_users_repo import SqliteClientesUsersRepo
        from auth.sessao_service import SessaoService
        from auth.tenants_repo import SqliteTenantsRepo
        from auth import cliente_routes as mod
        from flask import Flask

        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(self._tmp.name) / "tenants.db")
        self.tenants = SqliteTenantsRepo(db_path)
        self.users_repo = SqliteClientesUsersRepo(db_path)
        site = self.tenants.criar_site(
            slug="acme", nome="ACME", ambiente="development",
            dominios=["https://acme.test"], plano="free", bucket_name="cliente_acme",
        )
        self.site_id = site.id

        self.svc = SessaoService(self.users_repo, sessao_ttl_segundos=3600,
                                  magic_link_ttl_segundos=900)
        self.svc.criar_user(self.site_id, "dan@acme.com", senha="secret-123", papel="admin")

        self.client_grafana = _client_mock()
        self.sync = GrafanaSyncService(self.client_grafana)

        os.environ["COOKIE_SECURE"] = "false"
        app = Flask(__name__)
        # Reset module-level singletons antes de configurar
        mod._svc_instance = None
        mod._email_sender = MagicMock()
        mod._grafana_sync = None
        mod._tenants_repo = None
        mod.configurar(self.svc, email_sender=mod._email_sender,
                       grafana_sync=self.sync, tenants_repo=self.tenants)
        app.register_blueprint(mod.cliente_auth_bp)
        app.testing = True
        self.app = app
        self.test_client = app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def _login(self):
        r = self.test_client.post("/cliente/auth/login",
                                  json={"email": "dan@acme.com", "senha": "secret-123"})
        self.assertEqual(r.status_code, 200)

    def test_gate_dispara_sync_grafana_com_org_correta(self):
        self._login()
        r = self.test_client.get("/cliente/auth/gate")
        self.assertEqual(r.status_code, 200)
        # Sync deve ter sido chamada com (site_id, cliente_<slug>)
        self.client_grafana.get_org_by_name.assert_called_with("cliente_acme")

    def test_gate_continua_funcionando_se_sync_falhar(self):
        self.client_grafana.get_org_by_name.side_effect = RuntimeError("grafana 500")
        self._login()
        r = self.test_client.get("/cliente/auth/gate")
        # Sync falhou mas /gate retornou 200 + header — cookie vale.
        # X-WEBAUTH-USER e o slug do site (resolvido via _tenants_repo,
        # independente da Grafana API). Valor compativel com o filtro
        # `r.site_slug == "${__user.login}"` dos dashboards.
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-WEBAUTH-USER"), "acme")

    def test_gate_sem_grafana_sync_configurado_nao_chama_nada(self):
        from auth import cliente_routes as mod
        mod._grafana_sync = None
        mod._tenants_repo = None
        self._login()
        r = self.test_client.get("/cliente/auth/gate")
        self.assertEqual(r.status_code, 200)
        self.client_grafana.get_org_by_name.assert_not_called()

    def test_gate_chamadas_repetidas_usam_cache(self):
        self._login()
        for _ in range(5):
            self.test_client.get("/cliente/auth/gate")
        # Apenas 1 sync de fato (cache TTL).
        self.assertEqual(self.client_grafana.get_org_by_name.call_count, 1)


if __name__ == "__main__":
    unittest.main()
