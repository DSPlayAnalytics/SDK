"""Cobre bucket-per-cliente sprint 1:

  - SitesCache resolve site_id -> bucket_name e cacheia.
  - SitesCache.invalidar() forca refetch.
  - ServicoIngestao roteia escrita para o bucket dedicado quando ha sites_cache.
  - Sem sites_cache (compat legado): nao passa kwarg bucket.
  - Sem bucket_name no site: registra warning + escreve no bucket default.
  - validador rejeita app_id/ambiente ausentes.
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
from ingestao.idempotencia import resetar_tudo as resetar_idempotencia  # noqa: E402
from ingestao.servico_ingestao import ServicoIngestao  # noqa: E402


# ----------------------------- helpers -----------------------------

def _payload(id_registro: str | None = None):
    agora = int(time.time() * 1000)
    return {
        "id_registro": id_registro or f"reg-{uuid.uuid4()}",
        "app_id": "acme-frontend",
        "ambiente": "production",
        "timestamp_inicial": agora - 5000,
        "timestamp_final": agora,
        "paginas": {
            "/": [{
                "eventos": [
                    {"tipo": "page_view", "timestamp": agora - 4500,
                     "dados": {"page_id": "/", "path": "/"}},
                    {"tipo": "click", "timestamp": agora - 4000,
                     "dados": {"x": 1, "y": 2, "elemento_id": "btn"}},
                    {"tipo": "web_vital", "timestamp": agora - 3000,
                     "dados": {"nome": "LCP", "valor": 1800, "rating": "good"}},
                    {"tipo": "custom", "timestamp": agora - 2000,
                     "dados": {"nome": "checkout_iniciado", "propriedades": {"valor": 99}}},
                ],
                "visualizacoes": 1,
                "segundos": 5,
                "timestamp_inicial": agora - 5000,
                "timestamp_final": agora,
            }],
        },
    }


class CapturadorComBucket:
    """Capturador que armazena (metric, bucket) para inspecao."""

    def __init__(self):
        self.temporais: list[tuple] = []
        self.vitais: list[tuple] = []
        self.customs: list[tuple] = []

    def write_temporal_metrics_async(self, metrica, bucket=None):
        self.temporais.append((metrica, bucket))

    def write_web_vital_async(self, metrica, bucket=None):
        self.vitais.append((metrica, bucket))

    def write_custom_event_async(self, metrica, bucket=None):
        self.customs.append((metrica, bucket))


class CapturadorLegado:
    """Capturador antigo SEM kwarg bucket — simula codigo pre-sprint-1."""

    def __init__(self):
        self.temporais = []

    def write_temporal_metrics_async(self, metrica):
        self.temporais.append(metrica)

    def write_web_vital_async(self, metrica):
        pass

    def write_custom_event_async(self, metrica):
        pass


# ----------------------------- SitesCache -----------------------------

class SitesCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_resolve_bucket_a_partir_do_repo(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development",
            dominios=[], plano="free", bucket_name="cliente_acme",
        )
        cache = SitesCache(self.repo)
        self.assertEqual(cache.obter_bucket(site.id), "cliente_acme")

    def test_retorna_none_quando_site_sem_bucket(self):
        site = self.repo.criar_site(
            slug="legacy", nome="Legacy", ambiente="development", dominios=[],
        )
        cache = SitesCache(self.repo)
        self.assertIsNone(cache.obter_bucket(site.id))

    def test_retorna_none_para_site_id_vazio_ou_inexistente(self):
        cache = SitesCache(self.repo)
        self.assertIsNone(cache.obter_bucket(None))
        self.assertIsNone(cache.obter_bucket(""))
        self.assertIsNone(cache.obter_bucket("nao-existe-uuid"))

    def test_cache_evita_segunda_consulta_em_janela_ttl(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            bucket_name="cliente_acme",
        )
        cache = SitesCache(self.repo, ttl_seconds=60)
        self.assertEqual(cache.obter_bucket(site.id), "cliente_acme")
        # Mudanca direta no banco; cache nao ve ate invalidar.
        self.repo.definir_bucket_name(site.id, "cliente_acme_v2")
        self.assertEqual(cache.obter_bucket(site.id), "cliente_acme")
        cache.invalidar(site.id)
        self.assertEqual(cache.obter_bucket(site.id), "cliente_acme_v2")

    def test_ttl_expirado_dispara_refetch(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            bucket_name="cliente_acme",
        )
        cache = SitesCache(self.repo, ttl_seconds=0)  # expira imediatamente
        cache.obter_bucket(site.id)
        self.repo.definir_bucket_name(site.id, "cliente_acme_v2")
        self.assertEqual(cache.obter_bucket(site.id), "cliente_acme_v2")


# ----------------------------- ServicoIngestao routing -----------------------------

class ServicoIngestaoBucketRoutingTests(unittest.TestCase):
    def setUp(self):
        resetar_idempotencia()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_ingest_roteia_para_bucket_dedicado(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            bucket_name="cliente_acme",
        )
        cap = CapturadorComBucket()
        servico = ServicoIngestao(influxdb_service=cap, sites_cache=SitesCache(self.repo))
        resumo = servico.ingerir(
            session_id="s1", data=_payload(),
            user_agent="ua", ip_address="1.2.3.4", site_id=site.id,
        )
        self.assertEqual(resumo.status, "success")
        self.assertEqual(len(cap.temporais), 1)
        _, bucket = cap.temporais[0]
        self.assertEqual(bucket, "cliente_acme")
        # Web vital e custom event tambem devem cair no bucket dedicado.
        self.assertEqual(cap.vitais[0][1], "cliente_acme")
        self.assertEqual(cap.customs[0][1], "cliente_acme")

    def test_site_sem_bucket_REJEITA_strict_routing(self):
        """Sprint 2 item 1: site identificado sem bucket -> reject (nao fallback).

        Antes (sprint 1): caia no bucket default, gerava log mas escrevia mesmo
        assim — leak entre tenants. Agora rejeita com BUCKET_NAO_PROVISIONADO.
        """
        site = self.repo.criar_site(
            slug="legacy", nome="Legacy", ambiente="development", dominios=[],
        )
        cap = CapturadorComBucket()
        servico = ServicoIngestao(influxdb_service=cap, sites_cache=SitesCache(self.repo))
        resumo = servico.ingerir(
            session_id="s1", data=_payload(),
            user_agent="ua", ip_address="1.2.3.4", site_id=site.id,
        )
        self.assertEqual(resumo.status, "error")
        self.assertEqual(resumo.code, "BUCKET_NAO_PROVISIONADO")
        self.assertFalse(resumo.retriable)
        # Importante: NADA foi persistido no Influx.
        self.assertEqual(cap.temporais, [])
        self.assertEqual(cap.vitais, [])
        self.assertEqual(cap.customs, [])

    def test_site_id_none_continua_caindo_no_default(self):
        """Compat: ingest sem site_id (legacy/dev sem auth) ainda funciona."""
        cap = CapturadorComBucket()
        servico = ServicoIngestao(influxdb_service=cap, sites_cache=SitesCache(self.repo))
        resumo = servico.ingerir(
            session_id="s1", data=_payload(),
            user_agent="ua", ip_address="1.2.3.4", site_id=None,
        )
        self.assertEqual(resumo.status, "success")
        self.assertEqual(len(cap.temporais), 1)
        _, bucket = cap.temporais[0]
        self.assertIsNone(bucket)

    def test_compat_capturador_legado_sem_kwarg_bucket(self):
        cap = CapturadorLegado()
        # sites_cache=None: nao tenta passar kwarg, capturador antigo continua funcionando
        servico = ServicoIngestao(influxdb_service=cap, sites_cache=None)
        resumo = servico.ingerir(
            session_id="s1", data=_payload(),
            user_agent="ua", ip_address="1.2.3.4", site_id=None,
        )
        self.assertEqual(resumo.status, "success")
        self.assertEqual(len(cap.temporais), 1)

    def test_ingestao_sem_site_id_nao_consulta_cache(self):
        cap = CapturadorComBucket()

        class CacheFalhante:
            chamadas = 0
            def obter_bucket(self, site_id):
                CacheFalhante.chamadas += 1
                raise RuntimeError("nao deveria ser chamado")

        servico = ServicoIngestao(influxdb_service=cap, sites_cache=CacheFalhante())
        servico.ingerir(
            session_id="s1", data=_payload(),
            user_agent="ua", ip_address="1.2.3.4", site_id=None,
        )
        self.assertEqual(CacheFalhante.chamadas, 0)
        _, bucket = cap.temporais[0]
        self.assertIsNone(bucket)


# ----------------------------- TenantsRepo.bucket_name CRUD -----------------------------

class TenantsRepoBucketTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_criar_site_persiste_bucket_name(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            bucket_name="cliente_acme",
        )
        self.assertEqual(site.bucket_name, "cliente_acme")
        recarregado = self.repo.obter_site(site.id)
        self.assertEqual(recarregado.bucket_name, "cliente_acme")

    def test_obter_site_por_bucket(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
            bucket_name="cliente_acme",
        )
        achado = self.repo.obter_site_por_bucket("cliente_acme")
        self.assertIsNotNone(achado)
        self.assertEqual(achado.id, site.id)
        self.assertIsNone(self.repo.obter_site_por_bucket("nao-existe"))

    def test_definir_bucket_name_atualiza_site(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="development", dominios=[],
        )
        self.assertIsNone(site.bucket_name)
        self.repo.definir_bucket_name(site.id, "cliente_acme")
        self.assertEqual(self.repo.obter_site(site.id).bucket_name, "cliente_acme")

    def test_bucket_name_unico(self):
        self.repo.criar_site(
            slug="a", nome="A", ambiente="development", dominios=[], bucket_name="cliente_x",
        )
        with self.assertRaises(Exception):
            self.repo.criar_site(
                slug="b", nome="B", ambiente="development", dominios=[], bucket_name="cliente_x",
            )


if __name__ == "__main__":
    unittest.main()
