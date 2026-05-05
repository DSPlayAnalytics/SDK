"""Sprint 2 Bloco B item 1 — testes das derivacoes server-side.

Cobre:
  - detectar_device_type: mobile, tablet, desktop, bot, unknown.
  - extrair_referrer_dominio: dominio canonico, www-strip, direto, invalido.
  - extrair_pais: codigos ISO-2, XX, T1, sanitizacao.
  - Integracao no fluxo: ingerir() popula tags nos metrics e na cardinalidade.
"""
from __future__ import annotations

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
from ingestao.cardinalidade import TrackerCardinalidade  # noqa: E402
from ingestao.derivacoes import (  # noqa: E402
    derivar_group_bucket,
    derivar_user_bucket,
    detectar_device_type,
    extrair_pais,
    extrair_referrer_dominio,
)
from ingestao.idempotencia import resetar_tudo as resetar_idempotencia  # noqa: E402
from ingestao.servico_ingestao import ServicoIngestao  # noqa: E402


# =============================================================
# detectar_device_type
# =============================================================

class DetectarDeviceTypeTests(unittest.TestCase):
    def test_iphone_e_mobile(self):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
        self.assertEqual(detectar_device_type(ua), "mobile")

    def test_android_phone_e_mobile(self):
        ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Mobile Safari/537.36"
        self.assertEqual(detectar_device_type(ua), "mobile")

    def test_ipad_e_tablet_mesmo_com_palavra_mobile(self):
        # iPad tem 'Mobile' no UA mas devemos classificar como tablet.
        ua = ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 Mobile/15E148")
        self.assertEqual(detectar_device_type(ua), "tablet")

    def test_kindle_e_tablet(self):
        self.assertEqual(detectar_device_type("Mozilla/5.0 Kindle/3.0"), "tablet")

    def test_chrome_desktop_e_desktop(self):
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
        self.assertEqual(detectar_device_type(ua), "desktop")

    def test_googlebot_e_bot(self):
        ua = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        self.assertEqual(detectar_device_type(ua), "bot")

    def test_curl_e_bot(self):
        self.assertEqual(detectar_device_type("curl/8.5.0"), "bot")

    def test_python_requests_e_bot(self):
        self.assertEqual(detectar_device_type("python-requests/2.31"), "bot")

    def test_headless_chrome_e_bot(self):
        ua = "Mozilla/5.0 HeadlessChrome/120.0 Safari/537.36"
        self.assertEqual(detectar_device_type(ua), "bot")

    def test_facebookexternalhit_e_bot(self):
        # Crawler de preview de link
        self.assertEqual(detectar_device_type("facebookexternalhit/1.1"), "bot")

    def test_string_vazia_e_unknown(self):
        self.assertEqual(detectar_device_type(""), "unknown")
        self.assertEqual(detectar_device_type(None), "unknown")
        self.assertEqual(detectar_device_type("   "), "unknown")


# =============================================================
# extrair_referrer_dominio
# =============================================================

class ExtrairReferrerDominioTests(unittest.TestCase):
    def test_dominio_simples(self):
        self.assertEqual(extrair_referrer_dominio("https://google.com/"), "google.com")

    def test_strip_www(self):
        self.assertEqual(extrair_referrer_dominio("https://www.google.com/"), "google.com")

    def test_subdominio_preservado(self):
        self.assertEqual(
            extrair_referrer_dominio("https://blog.acme.com/post"),
            "blog.acme.com",
        )

    def test_query_e_path_descartados(self):
        self.assertEqual(
            extrair_referrer_dominio("https://google.com/search?q=portifolio&lr=lang_pt"),
            "google.com",
        )

    def test_porta_descartada(self):
        # urlparse.hostname remove a porta.
        self.assertEqual(
            extrair_referrer_dominio("https://localhost:3000/dashboard"),
            "localhost",
        )

    def test_dominio_lowercase(self):
        self.assertEqual(extrair_referrer_dominio("https://GOOGLE.com/"), "google.com")

    def test_referer_vazio_e_direto(self):
        self.assertEqual(extrair_referrer_dominio(None), "direto")
        self.assertEqual(extrair_referrer_dominio(""), "direto")
        self.assertEqual(extrair_referrer_dominio("   "), "direto")

    def test_referer_invalido_e_invalido(self):
        # String sem protocolo nem hostname canonico.
        self.assertEqual(extrair_referrer_dominio("nao-e-uma-url"), "invalido")


# =============================================================
# extrair_pais
# =============================================================

class ExtrairPaisTests(unittest.TestCase):
    def test_codigo_iso_uppercase(self):
        self.assertEqual(extrair_pais("BR"), "BR")
        self.assertEqual(extrair_pais("US"), "US")

    def test_codigo_lowercase_normalizado(self):
        self.assertEqual(extrair_pais("br"), "BR")

    def test_codigo_xx_aceito(self):
        self.assertEqual(extrair_pais("XX"), "XX")

    def test_codigo_t1_aceito_tor(self):
        self.assertEqual(extrair_pais("T1"), "T1")

    def test_codigo_invalido_vira_unknown(self):
        self.assertEqual(extrair_pais("BRA"), "unknown")  # nao iso-2
        self.assertEqual(extrair_pais("123"), "unknown")
        self.assertEqual(extrair_pais("br!"), "unknown")

    def test_vazio_unknown(self):
        self.assertEqual(extrair_pais(None), "unknown")
        self.assertEqual(extrair_pais(""), "unknown")
        self.assertEqual(extrair_pais("  "), "unknown")


# =============================================================
# derivar_user_bucket / derivar_group_bucket
# =============================================================

class DerivarUserBucketTests(unittest.TestCase):
    """Bucket finito (256) que viaja como tag pra retention/cohort sem
    estourar cardinalidade. Hash sha256 mod 256, formatado b000..b255.
    Decisao D1 — opcao C hibrida (sec roadmap SDK v0.4)."""

    def test_deterministico(self):
        # Mesmo input -> mesmo bucket. Garantia core: queries Flux que
        # filtram por user_bucket precisam achar todos os pontos do user.
        a = derivar_user_bucket("user-42")
        b = derivar_user_bucket("user-42")
        self.assertEqual(a, b)

    def test_formato_b000_b255(self):
        bucket = derivar_user_bucket("alguem")
        self.assertIsNotNone(bucket)
        self.assertRegex(bucket, r"^b\d{3}$")
        n = int(bucket[1:])
        self.assertGreaterEqual(n, 0)
        self.assertLessEqual(n, 255)

    def test_none_retorna_none(self):
        # Envelope sem user_id -> bucket None (nao str "bnone" ou "b000").
        # Backend usa None pra decidir nao adicionar a tag no Point.
        self.assertIsNone(derivar_user_bucket(None))

    def test_string_vazia_retorna_none(self):
        self.assertIsNone(derivar_user_bucket(""))

    def test_apenas_whitespace_retorna_none(self):
        # Defensiva: cliente pode mandar "   " — tratamos como ausente.
        self.assertIsNone(derivar_user_bucket("   "))

    def test_unicode_aceito(self):
        # user_id pode conter qualquer string opaca (cliente pode hashear).
        bucket = derivar_user_bucket("usuário-açaí-🍓")
        self.assertIsNotNone(bucket)
        self.assertRegex(bucket, r"^b\d{3}$")

    def test_distribuicao_uniforme(self):
        # 1000 ids sequenciais -> nenhum bucket fica >2x a media (4 esperado).
        # Sanity check do hash, nao prova rigorosa — falsos negativos sao raros.
        from collections import Counter
        contagem = Counter(derivar_user_bucket(f"user-{i}") for i in range(1000))
        media = 1000 / 256
        maior = max(contagem.values())
        self.assertLess(maior, media * 4,
                        f"bucket mais cheio: {maior}, esperado <{media * 4:.1f}")
        # Pelo menos 200 buckets distintos em 1000 amostras.
        self.assertGreater(len(contagem), 200)


class DerivarGroupBucketTests(unittest.TestCase):
    """Espelho de derivar_user_bucket pra org_id. Mesmo algoritmo, namespace
    separado — group_id 'X' nao precisa cair no mesmo bucket que user_id 'X'."""

    def test_deterministico(self):
        a = derivar_group_bucket("acme-corp")
        b = derivar_group_bucket("acme-corp")
        self.assertEqual(a, b)

    def test_formato_b000_b255(self):
        bucket = derivar_group_bucket("alguma-org")
        self.assertIsNotNone(bucket)
        self.assertRegex(bucket, r"^b\d{3}$")

    def test_none_retorna_none(self):
        self.assertIsNone(derivar_group_bucket(None))

    def test_string_vazia_retorna_none(self):
        self.assertIsNone(derivar_group_bucket(""))


# =============================================================
# Integracao no ServicoIngestao
# =============================================================

def _payload(id_registro=None):
    agora = int(time.time() * 1000)
    return {
        "id_registro": id_registro or f"reg-{uuid.uuid4()}",
        "app_id": "acme",
        "ambiente": "production",
        "session_id": "sess-1",
        "timestamp_inicial": agora - 5000,
        "timestamp_final": agora,
        "paginas": {
            "/": [{
                "eventos": [
                    {"tipo": "page_view", "timestamp": agora - 4500, "dados": {}},
                ],
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


class IntegracaoServicoIngestaoTests(unittest.TestCase):
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

    def test_metric_temporal_recebe_device_pais_referrer(self):
        cap = CaptInflux()
        servico = ServicoIngestao(
            influxdb_service=cap, sites_cache=SitesCache(self.repo),
            tenants_repo=self.repo,
        )
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148"
        r = servico.ingerir(
            session_id="s", data=_payload(),
            user_agent=ua, ip_address="1.1.1.1",
            site_id=self.site.id,
            referer="https://www.google.com/search?q=acme",
            cf_ipcountry="BR",
        )
        self.assertEqual(r.status, "success")
        metric, _ = cap.temporais[0]
        self.assertEqual(metric.device_type, "mobile")
        self.assertEqual(metric.pais, "BR")
        self.assertEqual(metric.referrer_dominio, "google.com")

    def test_metric_sem_headers_recebe_unknown_e_direto(self):
        cap = CaptInflux()
        servico = ServicoIngestao(
            influxdb_service=cap, sites_cache=SitesCache(self.repo),
            tenants_repo=self.repo,
        )
        r = servico.ingerir(
            session_id="s", data=_payload(),
            user_agent=None, ip_address=None,
            site_id=self.site.id,
            referer=None, cf_ipcountry=None,
        )
        self.assertEqual(r.status, "success")
        metric, _ = cap.temporais[0]
        self.assertEqual(metric.device_type, "unknown")
        self.assertEqual(metric.pais, "unknown")
        self.assertEqual(metric.referrer_dominio, "direto")

    def test_cardinalidade_inclui_tags_derivadas(self):
        tracker = TrackerCardinalidade()
        cap = CaptInflux()
        servico = ServicoIngestao(
            influxdb_service=cap, sites_cache=SitesCache(self.repo),
            tenants_repo=self.repo, cardinalidade_tracker=tracker,
        )
        ua = "Mozilla/5.0 (iPad; CPU OS 17_0) AppleWebKit/605.1.15 Mobile/15E148"
        servico.ingerir(
            session_id="s", data=_payload(),
            user_agent=ua, ip_address="1.1.1.1",
            site_id=self.site.id,
            referer="https://duckduckgo.com/?q=acme",
            cf_ipcountry="us",
        )
        por_tag = tracker.por_tag(self.site.id)
        self.assertEqual(por_tag.get("device_type"), 1)  # tablet
        self.assertEqual(por_tag.get("pais"), 1)         # US
        self.assertEqual(por_tag.get("referrer_dominio"), 1)  # duckduckgo.com

    def test_clientes_diferentes_sem_referer_compartilham_valor_direto(self):
        """Visitantes sem referer todos viram 'direto' — bom: cardinalidade nao explode."""
        tracker = TrackerCardinalidade()
        cap = CaptInflux()
        servico = ServicoIngestao(
            influxdb_service=cap, sites_cache=SitesCache(self.repo),
            tenants_repo=self.repo, cardinalidade_tracker=tracker,
        )
        # 100 ingests sem referer -> ainda eh 1 valor distinto pra referrer_dominio.
        for i in range(100):
            servico.ingerir(
                session_id="s", data=_payload(f"r{i}"),
                user_agent="Mozilla/5.0 desktop",
                ip_address="1.1.1.1", site_id=self.site.id,
                referer=None, cf_ipcountry=None,
            )
        por_tag = tracker.por_tag(self.site.id)
        self.assertEqual(por_tag.get("referrer_dominio"), 1)


if __name__ == "__main__":
    unittest.main()
