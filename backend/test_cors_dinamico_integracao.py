"""Integracao Flask: hooks before/after_request implementam CORS pra origens dinamicas.

Cobre OPTIONS preflight + GET/POST com Origin de cliente registrado em
site_dominios. Sem mockar app.py — usa um mini-Flask app que reproduz a
mesma estrutura das hooks.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, make_response, request

from auth.origins_dinamicos import OriginsDinamicos


def _construir_app(tenants_repo, origins_estaticos):
    """Mini-app que registra os mesmos hooks do backend principal."""
    app = Flask(__name__)
    app.testing = True

    cors_origins_set = frozenset(o.rstrip("/") for o in origins_estaticos)
    origins_dinamicos = OriginsDinamicos(
        origins_estaticos=origins_estaticos,
        tenants_repo=tenants_repo,
        ttl_segundos=60,
    )

    @app.before_request
    def preflight():
        if request.method != "OPTIONS":
            return None
        origin = request.headers.get("Origin")
        if not origin:
            return None
        normalizado = origin.rstrip("/")
        if normalizado in cors_origins_set:
            return None
        if not origins_dinamicos.permitido(normalizado):
            return None
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Max-Age"] = "86400"
        resp.headers["Vary"] = "Origin"
        return resp

    @app.after_request
    def resposta(resp):
        if resp.headers.get("Access-Control-Allow-Origin"):
            return resp
        origin = request.headers.get("Origin")
        if not origin:
            return resp
        normalizado = origin.rstrip("/")
        if normalizado in cors_origins_set:
            return resp
        if not origins_dinamicos.permitido(normalizado):
            return resp
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        existing = resp.headers.get("Vary", "")
        resp.headers["Vary"] = ("Origin, " + existing) if existing else "Origin"
        return resp

    @app.route("/ping", methods=["GET", "POST", "OPTIONS"])
    def ping():
        return jsonify({"ok": True})

    return app


class CorsDinamicoIntegracaoTest(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.app = _construir_app(
            tenants_repo=self.repo,
            origins_estaticos=["https://app.dsplayground.com.br"],
        )
        self.client = self.app.test_client()

    def test_preflight_dinamico_registrado_responde_204_com_cors(self):
        self.repo.dominio_existe.return_value = True
        r = self.client.options(
            "/ping",
            headers={
                "Origin": "https://acme.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "https://acme.com")
        self.assertEqual(r.headers.get("Access-Control-Allow-Credentials"), "true")
        self.assertIn("Origin", r.headers.get("Vary", ""))

    def test_preflight_inclui_PATCH_nos_methods(self):
        # /cliente/auth/senha e /email usam PATCH — sem isso navegador
        # bloqueia request com "Method PATCH is not allowed by
        # Access-Control-Allow-Methods in preflight response".
        self.repo.dominio_existe.return_value = True
        r = self.client.options(
            "/ping",
            headers={
                "Origin": "https://acme.com",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        self.assertEqual(r.status_code, 204)
        methods = r.headers.get("Access-Control-Allow-Methods", "")
        self.assertIn("PATCH", methods, f"PATCH ausente em: {methods}")

    def test_preflight_origin_nao_registrado_sem_headers_cors(self):
        self.repo.dominio_existe.return_value = False
        r = self.client.options(
            "/ping",
            headers={"Origin": "https://hacker.com"},
        )
        # 200 default do Flask (rota aceita OPTIONS), mas SEM ACAO de CORS
        self.assertNotEqual(r.headers.get("Access-Control-Allow-Origin"), "https://hacker.com")

    def test_get_origin_registrado_response_tem_headers_cors(self):
        self.repo.dominio_existe.return_value = True
        r = self.client.get(
            "/ping",
            headers={"Origin": "https://acme.com"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "https://acme.com")
        self.assertEqual(r.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_get_origin_nao_registrado_response_sem_headers_cors(self):
        self.repo.dominio_existe.return_value = False
        r = self.client.get(
            "/ping",
            headers={"Origin": "https://hacker.com"},
        )
        self.assertEqual(r.status_code, 200)  # backend responde, mas browser bloqueia
        self.assertNotEqual(r.headers.get("Access-Control-Allow-Origin"), "https://hacker.com")

    def test_get_sem_origin_response_sem_cors(self):
        r = self.client.get("/ping")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))

    def test_get_origin_estatico_nao_dispara_lookup_dinamico(self):
        # Origin que ja eh estatico — repo.dominio_existe NUNCA chamado
        r = self.client.get(
            "/ping",
            headers={"Origin": "https://app.dsplayground.com.br"},
        )
        self.assertEqual(r.status_code, 200)
        self.repo.dominio_existe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
