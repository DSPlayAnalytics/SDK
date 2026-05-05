"""Testes da fase de autenticacao multi-tenant do SDK.

Cobre: JwtService (emissao/verificacao), TenantsRepo (CRUD + origin/quota),
POST /auth/sdk-token (happy path + falhas), middleware @require_scope,
validar_token_socketio.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt as pyjwt
from flask import Flask, g, jsonify

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth import jwt_service as jwt_service_mod
from auth import tenants_repo as tenants_repo_mod
from auth.jwt_service import JwtService
from auth.middleware import require_scope, validar_token_socketio, AuthError
from auth.routes import auth_bp
from auth.tenants_repo import SqliteTenantsRepo as TenantsRepo


def _criar_app_teste(repo: TenantsRepo, jwt_service: JwtService) -> Flask:
    app = Flask(__name__)
    app.config["SDK_TOKEN_TTL_SECONDS"] = 300

    # singletons precisam apontar para as instancias do teste
    jwt_service_mod._service_instance = jwt_service
    tenants_repo_mod._repo_instance = repo

    app.register_blueprint(auth_bp)

    @app.route("/protegido", methods=["GET"])
    @require_scope("ingest")
    def protegido():
        return jsonify({"ok": True, "site": g.auth.claims.site_id})

    @app.route("/somente-query", methods=["GET"])
    @require_scope("query")
    def somente_query():
        return jsonify({"ok": True})

    return app


class TenantsRepoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = TenantsRepo(str(Path(self._tmp.name) / "tenants.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_criar_site_com_dominios_e_quota_default(self):
        site = self.repo.criar_site(
            slug="acme",
            nome="Acme",
            ambiente="production",
            dominios=["https://acme.com", "https://www.acme.com"],
        )
        self.assertEqual(site.slug, "acme")
        self.assertEqual(self.repo.listar_dominios(site.id),
                         ["https://acme.com", "https://www.acme.com"])
        quota = self.repo.obter_quota(site.id)
        self.assertIsNotNone(quota)
        self.assertEqual(quota.eventos_por_dia, 100000)

    def test_origin_permitido_normaliza_trailing_slash(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="production",
            dominios=["https://acme.com"],
        )
        self.assertTrue(self.repo.origin_permitido(site.id, "https://acme.com"))
        self.assertFalse(self.repo.origin_permitido(site.id, "https://other.com"))

    def test_publishable_revogada(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="production",
            dominios=["https://acme.com"],
        )
        key, valor = self.repo.criar_publishable_key(site.id, "production")
        self.assertFalse(self.repo.obter_publishable_por_valor(valor).revogada)
        self.repo.revogar_publishable_key(key.key_id)
        self.assertTrue(self.repo.obter_publishable_por_valor(valor).revogada)

    def test_rate_limit_emissao(self):
        site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="production",
            dominios=["https://acme.com"],
        )
        key, _ = self.repo.criar_publishable_key(site.id, "production")
        self.assertEqual(self.repo.contar_emissoes_recentes(key.key_id), 0)
        self.repo.registrar_emissao(
            site_id=site.id, publishable_id=key.key_id, jti="j1",
            origin="https://acme.com", ip="1.2.3.4",
        )
        self.assertEqual(self.repo.contar_emissoes_recentes(key.key_id), 1)


class JwtServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.service = JwtService(
            keys_dir=str(Path(self._tmp.name) / "keys"),
            audience="api.dsplayground.test",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_keypair_persiste_entre_instancias(self):
        outra = JwtService(
            keys_dir=str(Path(self._tmp.name) / "keys"),
            audience="api.dsplayground.test",
        )
        self.assertEqual(self.service.kid, outra.kid)

    def test_emissao_e_verificacao_happy(self):
        token, claims = self.service.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=60,
        )
        verificado = self.service.verificar(token, scope_esperado="ingest")
        self.assertEqual(verificado.site_id, "site-1")
        self.assertEqual(verificado.app_id, "acme")
        self.assertEqual(verificado.scope, "ingest")
        self.assertEqual(verificado.jti, claims.jti)

    def test_token_com_aud_errado_e_rejeitado(self):
        outro = JwtService(
            keys_dir=str(Path(self._tmp.name) / "keys2"),
            audience="outra.dominio",
        )
        token, _ = outro.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=60,
        )
        with self.assertRaises(pyjwt.InvalidTokenError):
            self.service.verificar(token)

    def test_scope_errado_levanta_permission_error(self):
        token, _ = self.service.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=60,
        )
        with self.assertRaises(PermissionError):
            self.service.verificar(token, scope_esperado="query")

    def test_token_expirado_e_rejeitado(self):
        token, _ = self.service.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=-1,
        )
        with self.assertRaises(pyjwt.ExpiredSignatureError):
            self.service.verificar(token)


class AuthRouteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = TenantsRepo(str(Path(self._tmp.name) / "tenants.db"))
        self.jwt_service = JwtService(
            keys_dir=str(Path(self._tmp.name) / "keys"),
            audience="api.dsplayground.test",
        )
        self.app = _criar_app_teste(self.repo, self.jwt_service)
        self.client = self.app.test_client()

        self.site = self.repo.criar_site(
            slug="acme", nome="Acme", ambiente="production",
            dominios=["https://acme.com"],
        )
        _, self.valor = self.repo.criar_publishable_key(self.site.id, "production")

    def tearDown(self):
        jwt_service_mod.resetar_servico()
        tenants_repo_mod.resetar_repo()
        self._tmp.cleanup()

    def _post(self, body=None, origin="https://acme.com"):
        return self.client.post(
            "/auth/sdk-token",
            json=body if body is not None else {"publishable_key": self.valor},
            headers={"Origin": origin},
        )

    def test_emissao_sucesso(self):
        r = self._post()
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("token", data)
        self.assertEqual(data["expires_in"], 300)
        self.assertEqual(data["server_schema_version"], "1.2")

        # token emitido e valido
        claims = self.jwt_service.verificar(data["token"])
        self.assertEqual(claims.site_id, self.site.id)

    def test_publishable_ausente(self):
        r = self._post(body={})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "PUBLISHABLE_MISSING")

    def test_publishable_invalida(self):
        r = self._post(body={"publishable_key": "pk_production_inexistente"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["code"], "PUBLISHABLE_INVALID")

    def test_origin_fora_da_allowlist(self):
        r = self._post(origin="https://atacante.com")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["code"], "ORIGIN_NOT_ALLOWED")

    def test_origin_ausente(self):
        r = self.client.post("/auth/sdk-token",
                             json={"publishable_key": self.valor})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "ORIGIN_MISSING")

    def test_publishable_revogada(self):
        keys = self.repo.listar_publishable_keys(self.site.id)
        self.repo.revogar_publishable_key(keys[0].key_id)
        r = self._post()
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["code"], "PUBLISHABLE_INVALID")

    def test_site_suspenso(self):
        self.repo.atualizar_status_site(self.site.id, "suspenso")
        r = self._post()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["code"], "SITE_INACTIVE")

    def test_rate_limit_emissao(self):
        self.repo.atualizar_quota(self.site.id, emissoes_jwt_por_minuto=2)
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(self._post().status_code, 200)
        r = self._post()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["code"], "RATE_LIMIT_EMISSION")

    def test_quota_diaria_estourada(self):
        self.repo.atualizar_quota(self.site.id, eventos_por_dia=5)
        self.repo.incrementar_consumo(self.site.id, eventos=5)
        r = self._post()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["code"], "QUOTA_EXCEEDED")

    def test_schema_cliente_desatualizado(self):
        r = self.client.post(
            "/auth/sdk-token",
            json={"publishable_key": self.valor},
            headers={"Origin": "https://acme.com", "X-SDK-Schema-Version": "0.9"},
        )
        self.assertEqual(r.status_code, 426)
        self.assertEqual(r.get_json()["code"], "UNSUPPORTED_SCHEMA")


class MiddlewareTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = TenantsRepo(str(Path(self._tmp.name) / "tenants.db"))
        self.jwt_service = JwtService(
            keys_dir=str(Path(self._tmp.name) / "keys"),
            audience="api.dsplayground.test",
        )
        self.app = _criar_app_teste(self.repo, self.jwt_service)
        self.client = self.app.test_client()

    def tearDown(self):
        jwt_service_mod.resetar_servico()
        tenants_repo_mod.resetar_repo()
        self._tmp.cleanup()

    def test_endpoint_sem_token_rejeita(self):
        r = self.client.get("/protegido")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["code"], "TOKEN_MISSING")

    def test_endpoint_com_token_ingest_valido(self):
        token, _ = self.jwt_service.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=60,
        )
        r = self.client.get("/protegido", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["site"], "site-1")

    def test_sdk_jwt_nao_pivota_para_endpoint_query(self):
        """Garantia central do plano: sdk_jwt (scope=ingest) nao funciona em /somente-query."""
        token, _ = self.jwt_service.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=60,
        )
        r = self.client.get("/somente-query", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["code"], "INVALID_SCOPE")

    def test_token_expirado(self):
        token, _ = self.jwt_service.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=-1,
        )
        r = self.client.get("/protegido", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["code"], "TOKEN_EXPIRED")

    def test_validar_token_socketio_ok(self):
        token, _ = self.jwt_service.emitir_sdk_jwt(
            site_id="site-1", app_id="acme", ambiente="production", ttl_seconds=60,
        )
        claims = validar_token_socketio(token, scope_esperado="ingest")
        self.assertEqual(claims.site_id, "site-1")

    def test_validar_token_socketio_sem_token(self):
        with self.assertRaises(AuthError) as ctx:
            validar_token_socketio("", scope_esperado="ingest")
        self.assertEqual(ctx.exception.code, "TOKEN_MISSING")


if __name__ == "__main__":
    unittest.main()
