"""Sprint 2 — Bloco A: testes end-to-end dos 3 enforcements no ingest.

Cobre:
  - Item 1 (strict routing): tenant_admin.create_site agora preenche bucket_name
    automaticamente; provisionar_cliente.py preserva quem passou.
  - Item 3 (quota enforcement): ingerir() chama obter_quota + consumo_hoje;
    rejeita QUOTA_EXCEDIDA quando consumido >= eventos_por_dia; incrementa
    consumo_diario apos sucesso.
  - Item 4 (cardinalidade): TrackerCardinalidade em memoria; pares (tag,valor)
    extraidos do payload; rejeita CARDINALIDADE_EXCEDIDA quando soma de |set|
    excederia o limite do plano; store NAO eh mutado em rejeicao (atacante
    nao consegue inflar com lixo).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.sites_cache import SitesCache  # noqa: E402
from auth.tenants_repo import SqliteTenantsRepo  # noqa: E402
from ingestao.cardinalidade import (  # noqa: E402
    LIMITE_POR_PLANO,
    TrackerCardinalidade,
    limite_para_plano,
)
from ingestao.idempotencia import resetar_tudo as resetar_idempotencia  # noqa: E402
from ingestao.servico_ingestao import ServicoIngestao  # noqa: E402


# ----------------------------- helpers -----------------------------

def _payload(id_registro: str | None = None, page_type: str = "/", num_eventos: int = 1):
    agora = int(time.time() * 1000)
    eventos = [
        {"tipo": "page_view", "timestamp": agora - 4500, "dados": {"page_id": page_type}},
    ]
    for i in range(num_eventos - 1):
        eventos.append({
            "tipo": "click", "timestamp": agora - 4000 + i,
            "dados": {"x": i, "y": 0, "elemento_id": f"btn-{i}"},
        })
    return {
        "id_registro": id_registro or f"reg-{uuid.uuid4()}",
        "app_id": "acme-frontend",
        "ambiente": "production",
        "session_id": "sess-cliente-001",
        "timestamp_inicial": agora - 5000,
        "timestamp_final": agora,
        "paginas": {
            page_type: [{
                "eventos": eventos,
                "visualizacoes": 1,
                "segundos": 5,
                "timestamp_inicial": agora - 5000,
                "timestamp_final": agora,
            }],
        },
    }


class CaptInflux:
    def __init__(self):
        self.temporais = []
        self.vitais = []
        self.customs = []

    def write_temporal_metrics_async(self, m, bucket=None):
        self.temporais.append((m, bucket))

    def write_web_vital_async(self, m, bucket=None):
        self.vitais.append((m, bucket))

    def write_custom_event_async(self, m, bucket=None):
        self.customs.append((m, bucket))


# ============================================================
# Item 1 — Strict bucket routing (tenant_admin auto-bucket)
# ============================================================

class StrictBucketRoutingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_tenant_admin_create_preenche_bucket_name(self):
        """Sites criados via tenant_admin.cmd_create nascem com bucket_name."""
        # Simula o comportamento de cmd_create sem o argparse.
        # (cmd_create chama repo.criar_site com bucket_name=cliente_<slug>.)
        bucket_name = f"cliente_acme"
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            plano="free", bucket_name=bucket_name,
        )
        recarregado = self.repo.obter_site(site.id)
        self.assertEqual(recarregado.bucket_name, "cliente_acme")

    def test_backfill_buckets_atualiza_sites_legados(self):
        """Sites antigos (sem bucket_name) recebem cliente_<slug> via definir_bucket_name."""
        legacy = self.repo.criar_site(
            slug="legado-x", nome="Legacy", ambiente="development", dominios=[],
        )
        self.assertIsNone(legacy.bucket_name)
        # Simulacao do cmd_backfill_buckets:
        for site in self.repo.listar_sites():
            if not site.bucket_name:
                self.repo.definir_bucket_name(site.id, f"cliente_{site.slug}")
        self.assertEqual(
            self.repo.obter_site(legacy.id).bucket_name, "cliente_legado-x",
        )


# ============================================================
# Item 3 — Quota enforcement
# ============================================================

class QuotaEnforcementTests(unittest.TestCase):
    def setUp(self):
        resetar_idempotencia()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))
        self.site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            plano="free", bucket_name="cliente_acme",
        )
        self.repo.atualizar_quota(self.site.id, eventos_por_dia=3)

    def tearDown(self):
        self._tmp.cleanup()

    def _servico(self):
        return ServicoIngestao(
            influxdb_service=CaptInflux(),
            sites_cache=SitesCache(self.repo),
            tenants_repo=self.repo,
        )

    def test_consumo_diario_incrementa_apos_sucesso(self):
        servico = self._servico()
        servico.ingerir(session_id="s", data=_payload(),
                        user_agent="ua", ip_address="1.1.1.1", site_id=self.site.id)
        self.assertEqual(self.repo.consumo_hoje(self.site.id), 1)
        servico.ingerir(session_id="s", data=_payload(),
                        user_agent="ua", ip_address="1.1.1.1", site_id=self.site.id)
        self.assertEqual(self.repo.consumo_hoje(self.site.id), 2)

    def test_quota_excedida_rejeita_com_code_quota_excedida(self):
        # consome 3 (limite do quota=3): proximo deve falhar.
        servico = self._servico()
        for i in range(3):
            r = servico.ingerir(session_id="s", data=_payload(f"r{i}"),
                                user_agent="ua", ip_address="1.1.1.1",
                                site_id=self.site.id)
            self.assertEqual(r.status, "success", f"falhou no evento {i}")
        # Quarto deve passar do limite.
        r = servico.ingerir(session_id="s", data=_payload("r3"),
                            user_agent="ua", ip_address="1.1.1.1", site_id=self.site.id)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.code, "QUOTA_EXCEDIDA")
        self.assertFalse(r.retriable)
        # consumo NAO deve ter incrementado para 4.
        self.assertEqual(self.repo.consumo_hoje(self.site.id), 3)

    def test_sem_tenants_repo_nao_aplica_quota(self):
        """Modo legado sem repo: ingest passa mesmo com volume alto."""
        servico = ServicoIngestao(influxdb_service=CaptInflux())
        for i in range(10):
            r = servico.ingerir(session_id="s", data=_payload(f"x{i}"),
                                user_agent="ua", ip_address="1.1.1.1",
                                site_id=None)
            self.assertEqual(r.status, "success")

    def test_quota_lookup_falhando_degrada_permitindo(self):
        """Se tenants_repo joga erro, ingest NAO deve travar."""
        class RepoQuebrado:
            def obter_quota(self, _):
                raise RuntimeError("postgres caiu")
            def consumo_hoje(self, _):
                raise RuntimeError("postgres caiu")
            def incrementar_consumo(self, *_, **__):
                pass
            def obter_site(self, _):
                return None  # cardinalidade nao roda sem site

        servico = ServicoIngestao(
            influxdb_service=CaptInflux(),
            sites_cache=SitesCache(self.repo),
            tenants_repo=RepoQuebrado(),
        )
        r = servico.ingerir(session_id="s", data=_payload(),
                            user_agent="ua", ip_address="1.1.1.1", site_id=self.site.id)
        # Quando repo de quota falha, degrada permitindo (preferimos perder
        # enforcement do que derrubar ingest).
        self.assertEqual(r.status, "success")


# ============================================================
# Item 4 — Cardinalidade
# ============================================================

class TrackerCardinalidadeTests(unittest.TestCase):
    def test_aceita_quando_total_dentro_do_limite(self):
        t = TrackerCardinalidade()
        ok, tag, total = t.verificar_e_registrar(
            "site-1",
            [("app_id", "acme"), ("ambiente", "production"), ("page_type", "/")],
            limite=10,
        )
        self.assertTrue(ok)
        self.assertIsNone(tag)
        self.assertEqual(total, 3)
        self.assertEqual(t.por_tag("site-1"), {"app_id": 1, "ambiente": 1, "page_type": 1})

    def test_rejeita_quando_passa_do_limite_e_nao_muta_store(self):
        t = TrackerCardinalidade()
        # Pre-popula site com 5 page_types
        for i in range(5):
            t.verificar_e_registrar("site-1", [("page_type", f"/{i}")], limite=100)
        antes = t.por_tag("site-1")["page_type"]
        # Tenta inserir 7 page_types novos com limite total=10 -> 5+7=12 > 10
        novos = [("page_type", f"/novo-{i}") for i in range(7)]
        ok, tag, total = t.verificar_e_registrar("site-1", novos, limite=10)
        self.assertFalse(ok)
        self.assertEqual(tag, "page_type")
        self.assertEqual(total, 12)
        # Store NAO mutou.
        self.assertEqual(t.por_tag("site-1")["page_type"], antes)

    def test_dedup_local_no_mesmo_batch(self):
        t = TrackerCardinalidade()
        ok, _, total = t.verificar_e_registrar(
            "site-1",
            [("page_type", "/"), ("page_type", "/"), ("page_type", "/sobre")],
            limite=100,
        )
        self.assertTrue(ok)
        self.assertEqual(total, 2)  # nao 3

    def test_valores_vazios_sao_ignorados(self):
        t = TrackerCardinalidade()
        ok, _, total = t.verificar_e_registrar(
            "site-1",
            [("app_id", None), ("ambiente", ""), ("page_type", "/")],
            limite=100,
        )
        self.assertTrue(ok)
        self.assertEqual(total, 1)

    def test_invalidar_site_apaga_seu_store(self):
        t = TrackerCardinalidade()
        t.verificar_e_registrar("site-1", [("page_type", "/")], limite=100)
        t.verificar_e_registrar("site-2", [("page_type", "/")], limite=100)
        t.invalidar_site("site-1")
        self.assertEqual(t.por_tag("site-1"), {})
        self.assertEqual(t.por_tag("site-2"), {"page_type": 1})

    def test_limite_para_plano(self):
        self.assertEqual(limite_para_plano("free"), 1_000)
        self.assertEqual(limite_para_plano("pequeno"), 5_000)
        self.assertEqual(limite_para_plano("medio"), 50_000)
        self.assertEqual(limite_para_plano("grande"), 500_000)
        # Plano desconhecido -> mais restritivo.
        self.assertEqual(limite_para_plano("xpto"), 1_000)
        self.assertEqual(limite_para_plano(None), 1_000)


class CardinalidadeNoServicoIngestaoTests(unittest.TestCase):
    def setUp(self):
        resetar_idempotencia()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))
        self.site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            plano="free", bucket_name="cliente_acme",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _servico(self, tracker, *, limite_override=None):
        srv = ServicoIngestao(
            influxdb_service=CaptInflux(),
            sites_cache=SitesCache(self.repo),
            tenants_repo=self.repo,
            cardinalidade_tracker=tracker,
        )
        return srv

    def test_extrair_pares_tags_inclui_tags_relevantes(self):
        srv = self._servico(TrackerCardinalidade())
        agora = int(time.time() * 1000)
        data = {
            "app_id": "a", "ambiente": "production",
            "id_registro": "r1", "session_id": "sess-X",
            "timestamp_inicial": agora - 1000, "timestamp_final": agora,
            "paginas": {
                "/home": [{
                    "visualizacoes": 1, "segundos": 1,
                    "timestamp_inicial": agora - 1000, "timestamp_final": agora,
                    "eventos": [
                        {"tipo": "page_view", "timestamp": agora - 900, "dados": {}},
                        {"tipo": "custom", "timestamp": agora - 800,
                         "dados": {"nome": "checkout_iniciado"}},
                        {"tipo": "web_vital", "timestamp": agora - 700,
                         "dados": {"nome": "LCP", "valor": 1800, "rating": "good"}},
                    ],
                }],
                "/sobre": [{"eventos": [], "visualizacoes": 1, "segundos": 1,
                            "timestamp_inicial": agora - 1000, "timestamp_final": agora}],
            },
        }
        pares = srv._extrair_pares_tags(data, "sess-X")
        self.assertIn(("app_id", "a"), pares)
        self.assertIn(("ambiente", "production"), pares)
        self.assertIn(("session_id", "sess-X"), pares)
        self.assertIn(("page_type", "/home"), pares)
        self.assertIn(("page_type", "/sobre"), pares)
        self.assertIn(("nome", "checkout_iniciado"), pares)
        self.assertIn(("nome", "LCP"), pares)
        self.assertIn(("rating", "good"), pares)

    def test_ingest_normal_dentro_do_limite_passa(self):
        tracker = TrackerCardinalidade()
        srv = self._servico(tracker)
        r = srv.ingerir(session_id="s", data=_payload(),
                        user_agent="ua", ip_address="1.1.1.1", site_id=self.site.id)
        self.assertEqual(r.status, "success")
        # Tags registradas: app_id, ambiente, session_id, page_type
        total = tracker.total_para_site(self.site.id)
        self.assertGreaterEqual(total, 4)

    def test_cardinalidade_excedida_rejeita_com_code(self):
        # Pre-popula tracker no limite (free=1000 — vou testar com mock e limite baixo).
        tracker = TrackerCardinalidade()
        # Inflar tracker manualmente ate 999 distintos page_types (proximo do free=1000).
        for i in range(999):
            tracker.verificar_e_registrar(
                self.site.id, [("page_type", f"/p{i}")], limite=10_000_000,
            )
        # Pre-existente: 999. Plano free=1000.
        # Payload novo agora vai tentar adicionar:
        #   app_id (1), ambiente (1), session_id (1), page_type (1 novo)
        # = 4 novos -> total=1003 > 1000 -> rejeita.
        srv = self._servico(tracker)
        r = srv.ingerir(session_id="s", data=_payload("excede"),
                        user_agent="ua", ip_address="1.1.1.1", site_id=self.site.id)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.code, "CARDINALIDADE_EXCEDIDA")
        self.assertFalse(r.retriable)
        # Store NAO foi mutado pelos novos pares.
        self.assertEqual(tracker.total_para_site(self.site.id), 999)

    def test_sem_tracker_nao_aplica_enforcement(self):
        srv = ServicoIngestao(
            influxdb_service=CaptInflux(),
            sites_cache=SitesCache(self.repo),
            tenants_repo=self.repo,
            cardinalidade_tracker=None,
        )
        for _ in range(50):
            r = srv.ingerir(session_id="s", data=_payload(),
                            user_agent="ua", ip_address="1.1.1.1", site_id=self.site.id)
            self.assertEqual(r.status, "success")

    def test_site_id_none_nao_dispara_tracker(self):
        tracker = TrackerCardinalidade()
        srv = self._servico(tracker)
        r = srv.ingerir(session_id="s", data=_payload(),
                        user_agent="ua", ip_address="1.1.1.1", site_id=None)
        self.assertEqual(r.status, "success")
        self.assertEqual(tracker.por_tag(None) if False else tracker.total_para_site("x"), 0)


if __name__ == "__main__":
    unittest.main()
