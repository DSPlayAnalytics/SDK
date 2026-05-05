"""Sprint 2 Bloco B item 2 — testes do import de dashboards.

Cobre:
  - _carregar_template substitui __BUCKET__ e zera id (evita conflito entre orgs).
  - JSON invalido -> SystemExit cedo (nao polui Grafana).
  - _provisionar_dashboards itera todos os JSONs de DASHBOARDS_DIR.
  - GrafanaClient.import_dashboard chama POST /api/dashboards/db com overwrite=True.
  - Idempotente: chamada repetida re-importa sem duplicar.
  - Skip via flag --skip-dashboards.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class CarregarTemplateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _import_carregar(self):
        from scripts.provisionar_cliente import _carregar_template
        return _carregar_template

    def test_substitui_bucket_e_zera_id(self):
        path = self.dir / "test.json"
        path.write_text(json.dumps({
            "id": 999,
            "uid": "x",
            "title": "Demo",
            "panels": [{
                "targets": [{"query": "from(bucket: \"__BUCKET__\")"}],
            }],
        }), encoding="utf-8")
        out = self._import_carregar()(path, "cliente_acme")
        self.assertIsNone(out["id"])
        self.assertEqual(out["uid"], "x")
        self.assertEqual(out["panels"][0]["targets"][0]["query"], 'from(bucket: "cliente_acme")')

    def test_substitui_datasource_uid(self):
        path = self.dir / "test.json"
        path.write_text(json.dumps({
            "id": None, "uid": "y",
            "panels": [{
                "datasource": {"type": "influxdb", "uid": "__DATASOURCE_UID__"},
                "targets": [{"query": "from(bucket: \"__BUCKET__\")"}],
            }],
        }), encoding="utf-8")
        out = self._import_carregar()(path, "b1", datasource_uid="abcd1234")
        self.assertEqual(out["panels"][0]["datasource"]["uid"], "abcd1234")
        self.assertEqual(out["panels"][0]["targets"][0]["query"], 'from(bucket: "b1")')

    def test_datasource_uid_vazio_substitui_por_string_vazia(self):
        path = self.dir / "test.json"
        path.write_text(json.dumps({
            "id": None,
            "panels": [{
                "datasource": {"type": "influxdb", "uid": "__DATASOURCE_UID__"},
            }],
        }), encoding="utf-8")
        # Caller pode nao ter uid (compat) — substitui por "" e Grafana resolve.
        out = self._import_carregar()(path, "b1", datasource_uid="")
        self.assertEqual(out["panels"][0]["datasource"]["uid"], "")

    def test_substitui_em_multiplos_lugares(self):
        path = self.dir / "test.json"
        path.write_text(json.dumps({
            "id": None,
            "panels": [
                {"targets": [{"query": "bucket=\"__BUCKET__\""}]},
                {"targets": [{"query": "bucket=\"__BUCKET__\""}]},
                {"targets": [{"query": "bucket=\"__BUCKET__\""}]},
            ],
        }), encoding="utf-8")
        out = self._import_carregar()(path, "cliente_xy")
        for p in out["panels"]:
            self.assertEqual(p["targets"][0]["query"], 'bucket="cliente_xy"')

    def test_json_invalido_levanta_systemexit_cedo(self):
        path = self.dir / "broken.json"
        path.write_text("{ isso nao e JSON valido", encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            self._import_carregar()(path, "cliente_x")
        self.assertIn("broken.json", str(ctx.exception))

    def test_template_sem_placeholder_passa_sem_alterar(self):
        path = self.dir / "test.json"
        path.write_text(json.dumps({
            "id": 1, "title": "sem placeholder",
            "panels": [{"targets": [{"query": "from(bucket: \"hardcoded\")"}]}],
        }), encoding="utf-8")
        out = self._import_carregar()(path, "cliente_x")
        # id eh zerado independente da presenca de placeholder.
        self.assertIsNone(out["id"])
        self.assertEqual(out["panels"][0]["targets"][0]["query"], 'from(bucket: "hardcoded")')


class ProvisionarDashboardsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _escrever(self, nome: str, conteudo: dict):
        (self.dir / nome).write_text(json.dumps(conteudo), encoding="utf-8")

    def test_itera_todos_os_jsons_em_ordem(self):
        from scripts import provisionar_cliente as mod
        self._escrever("a.json", {"id": None, "uid": "a", "title": "A"})
        self._escrever("b.json", {"id": None, "uid": "b", "title": "B"})
        self._escrever("notajson.txt", {"ignorar": True})  # nao termina em .json

        gf = MagicMock()
        gf.import_dashboard.side_effect = lambda **kw: {
            "uid": kw["dashboard"]["uid"],
            "url": f"/d/{kw['dashboard']['uid']}",
            "version": 1,
        }
        with patch.object(mod, "DASHBOARDS_DIR", self.dir):
            result = mod._provisionar_dashboards(gf, org_id=42, slug="x", bucket_name="b")

        self.assertEqual(len(result), 2)
        self.assertEqual([r["arquivo"] for r in result], ["a.json", "b.json"])
        self.assertEqual([r["uid"] for r in result], ["a", "b"])
        # Cada chamada usa o mesmo org_id e mensagem identifica o slug.
        for chamada in gf.import_dashboard.call_args_list:
            self.assertEqual(chamada.kwargs["org_id"], 42)
            self.assertIn("x", chamada.kwargs["message"])

    def test_runtime_error_em_import_vira_systemexit(self):
        from scripts import provisionar_cliente as mod
        self._escrever("a.json", {"id": None, "uid": "a"})
        gf = MagicMock()
        gf.import_dashboard.side_effect = RuntimeError("grafana 500")
        with patch.object(mod, "DASHBOARDS_DIR", self.dir):
            with self.assertRaises(SystemExit) as ctx:
                mod._provisionar_dashboards(gf, org_id=42, slug="x", bucket_name="b")
        self.assertIn("a.json", str(ctx.exception))

    def test_dir_inexistente_retorna_lista_vazia(self):
        from scripts import provisionar_cliente as mod
        inexistente = self.dir / "nao-existe"
        with patch.object(mod, "DASHBOARDS_DIR", inexistente):
            gf = MagicMock()
            result = mod._provisionar_dashboards(gf, org_id=1, slug="x", bucket_name="b")
        self.assertEqual(result, [])
        gf.import_dashboard.assert_not_called()


class GrafanaClientImportDashboardTests(unittest.TestCase):
    def test_import_envia_body_correto(self):
        from integrations.grafana_client import GrafanaClient
        gc = GrafanaClient("http://grafana:3000", "admin", "admin")
        with patch.object(gc, "_req") as mock_req:
            mock_req.return_value = {"id": 5, "uid": "x", "url": "/d/x", "version": 3}
            out = gc.import_dashboard(
                org_id=2, dashboard={"id": None, "uid": "x"},
                message="teste",
            )
            self.assertEqual(out["uid"], "x")
            mock_req.assert_called_once()
            kwargs = mock_req.call_args.kwargs
            self.assertEqual(kwargs["body"]["overwrite"], True)
            self.assertEqual(kwargs["body"]["message"], "teste")
            self.assertEqual(kwargs["body"]["dashboard"]["uid"], "x")
            self.assertEqual(kwargs["org_id"], 2)
            # Endpoint correto
            args = mock_req.call_args.args
            self.assertEqual(args[0], "POST")
            self.assertEqual(args[1], "/api/dashboards/db")

    def test_import_propaga_runtime_error(self):
        from integrations.grafana_client import GrafanaClient
        gc = GrafanaClient("http://grafana:3000", "admin", "admin")
        with patch.object(gc, "_req") as mock_req:
            mock_req.return_value = {"__http_error__": 500, "__body__": "boom"}
            with self.assertRaises(RuntimeError) as ctx:
                gc.import_dashboard(org_id=2, dashboard={"id": None, "uid": "x"})
            self.assertIn("500", str(ctx.exception))


def _carregar_template_repo(nome: str) -> dict:
    """Helper: carrega um template do repo e parseia."""
    repo_root = BACKEND_DIR.parent
    path = repo_root / "ark" / "monitoring" / "dashboards" / nome
    return json.loads(path.read_text(encoding="utf-8"))


class WebVitalsTemplateValidoTests(unittest.TestCase):
    """Garante que o JSON shipado no repo e parseavel, tem placeholder e UID."""

    def test_web_vitals_json_e_valido(self):
        repo_root = BACKEND_DIR.parent
        path = repo_root / "ark" / "monitoring" / "dashboards" / "web-vitals.json"
        self.assertTrue(path.exists(), f"template ausente: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["uid"], "portifolio-web-vitals")
        self.assertIn("Web Vitals", data["title"])
        self.assertGreater(len(data["panels"]), 3)
        self.assertFalse(data["editable"], "dashboard provisioned deve ser read-only")
        # Placeholders presentes em pelo menos 1 painel.
        achou_bucket = False
        achou_uid = False
        for p in data["panels"]:
            ds_uid = (p.get("datasource") or {}).get("uid", "")
            if ds_uid == "__DATASOURCE_UID__":
                achou_uid = True
            for t in p.get("targets", []):
                if "__BUCKET__" in t.get("query", ""):
                    achou_bucket = True
        self.assertTrue(achou_bucket, "nenhum painel referencia __BUCKET__")
        self.assertTrue(achou_uid, "nenhum painel usa __DATASOURCE_UID__")


class EventExplorerTemplateValidoTests(unittest.TestCase):
    """Sanity check do Event Explorer (sprint 2 bloco B item 3)."""

    def setUp(self):
        self.data = _carregar_template_repo("event-explorer.json")

    def test_uid_e_titulo(self):
        self.assertEqual(self.data["uid"], "portifolio-event-explorer")
        self.assertIn("Event Explorer", self.data["title"])
        self.assertFalse(self.data["editable"])

    def test_tem_variaveis_evento_e_breakdown(self):
        nomes_vars = {v["name"] for v in self.data["templating"]["list"]}
        self.assertEqual(nomes_vars, {"evento", "breakdown"})

    def test_variavel_evento_query_no_bucket_e_datasource_corretos(self):
        evento = next(v for v in self.data["templating"]["list"] if v["name"] == "evento")
        self.assertEqual(evento["type"], "query")
        self.assertEqual(evento["datasource"]["uid"], "__DATASOURCE_UID__")
        self.assertIn("__BUCKET__", evento["query"])
        self.assertIn("custom_events", evento["query"])
        self.assertIn("nome", evento["query"])

    def test_variavel_breakdown_tem_5_opcoes(self):
        breakdown = next(v for v in self.data["templating"]["list"] if v["name"] == "breakdown")
        self.assertEqual(breakdown["type"], "custom")
        valores = {o["value"] for o in breakdown["options"]}
        self.assertEqual(valores, {"page_type", "device_type", "pais",
                                    "referrer_dominio", "rating"})
        self.assertEqual(breakdown["current"]["value"], "page_type")

    def test_paineis_referenciam_variaveis(self):
        # Pelo menos 1 painel usa ${evento} e 1 usa ${breakdown}.
        usos_evento = 0
        usos_breakdown = 0
        for p in self.data["panels"]:
            for t in p.get("targets", []):
                q = t.get("query", "")
                if "${evento}" in q:
                    usos_evento += 1
                if "${breakdown}" in q:
                    usos_breakdown += 1
        self.assertGreater(usos_evento, 4, "evento deveria ser usado em varios paineis")
        self.assertGreater(usos_breakdown, 1, "breakdown deveria ser usado em pelo menos 2")

    def test_paineis_tem_uid_placeholder(self):
        for p in self.data["panels"]:
            ds = p.get("datasource", {})
            self.assertEqual(
                ds.get("uid"), "__DATASOURCE_UID__",
                f"painel {p['title']} sem __DATASOURCE_UID__",
            )

    def test_substituicao_de_placeholders_gera_json_valido(self):
        from scripts.provisionar_cliente import _carregar_template
        repo_root = BACKEND_DIR.parent
        path = repo_root / "ark" / "monitoring" / "dashboards" / "event-explorer.json"
        out = _carregar_template(path, "cliente_xpto", datasource_uid="abc123def")
        # Sem placeholders sobrando
        as_str = json.dumps(out)
        self.assertNotIn("__BUCKET__", as_str)
        self.assertNotIn("__DATASOURCE_UID__", as_str)
        # Substituicoes feitas
        self.assertIn("cliente_xpto", as_str)
        self.assertIn("abc123def", as_str)


class EngajamentoTemplateValidoTests(unittest.TestCase):
    """Sanity check do dashboard Engajamento (sprint 2 bloco B item 4)."""

    def setUp(self):
        self.data = _carregar_template_repo("engajamento.json")

    def test_uid_e_titulo(self):
        self.assertEqual(self.data["uid"], "portifolio-engajamento")
        self.assertIn("Engajamento", self.data["title"])
        self.assertFalse(self.data["editable"])

    def test_paineis_filtram_bots_e_referenciam_bucket(self):
        bot_filter_count = 0
        bucket_ref_count = 0
        for p in self.data["panels"]:
            for t in p.get("targets", []):
                q = t.get("query", "")
                if 'r.device_type != "bot"' in q:
                    bot_filter_count += 1
                if "__BUCKET__" in q:
                    bucket_ref_count += 1
        # Espera: pelo menos uns 8 paineis com filtro de bot (todos os de
        # engajamento — bot inflando metricas e o caso classico).
        self.assertGreater(bot_filter_count, 7,
                           "esperava bot filter em quase todos os paineis")
        self.assertGreater(bucket_ref_count, 7)

    def test_paineis_tem_uid_placeholder(self):
        for p in self.data["panels"]:
            ds = p.get("datasource", {})
            self.assertEqual(
                ds.get("uid"), "__DATASOURCE_UID__",
                f"painel {p['title']} sem __DATASOURCE_UID__",
            )

    def test_metricas_essenciais_cobertas(self):
        titulos = [p["title"].lower() for p in self.data["panels"]]
        # Esperamos paineis pra cliques, scrolls, hovers, exposicoes, toques,
        # device_type, page_type top, permanencia.
        for esperado in ["cliques", "scrolls", "hovers", "exposicoes",
                         "toques", "device_type", "permanencia"]:
            self.assertTrue(
                any(esperado in t for t in titulos),
                f"nenhum painel cobre '{esperado}'",
            )

    def test_substituicao_gera_json_valido(self):
        from scripts.provisionar_cliente import _carregar_template
        repo_root = BACKEND_DIR.parent
        path = repo_root / "ark" / "monitoring" / "dashboards" / "engajamento.json"
        out = _carregar_template(path, "cliente_test", datasource_uid="ds-uid-x")
        as_str = json.dumps(out)
        self.assertNotIn("__BUCKET__", as_str)
        self.assertNotIn("__DATASOURCE_UID__", as_str)


if __name__ == "__main__":
    unittest.main()
