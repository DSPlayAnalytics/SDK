"""Testes do blueprint /embed (token + dados).

Escopo (XP/TDD — cresce um teste por vez):
  - POST /embed/token
      - sem cookie cliente_session -> 401
      - cookie de user que NAO e dono do site_id alvo -> 403
      - cookie de user dono mas site_id inexistente -> 404
      - happy path -> 200 + JWT RS256 com claims:
          aud=embed.dsplayground.com.br, scope=embed:read,
          site_id, grafico_id, user_id, iss, exp, iat
      - ttl_segundos clampeado em [60, 600]
      - grafico_id fora da allow-list -> 400
  - GET /embed/dados/<site_id>/<grafico_id>
      - sem Authorization Bearer -> 401
      - JWT invalido -> 401
      - JWT com aud errado (ex: sdk_jwt) -> 401
      - site_id/grafico_id no path divergem do claim -> 403
      - happy path -> 200 + JSON com serie temporal mockada

Reusa SqliteTenantsRepo e SqliteClientesUsersRepo pra dispensar Postgres
em teste, e mocka InfluxDBService pra evitar dependencia de container.

Referencia: ark/docs/embed-iframe.md (Fase 1 — contratos tecnicos).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import jwt as pyjwt

from auth.clientes_users_repo import SqliteClientesUsersRepo
from auth.embed_jwt_service import EMBED_AUDIENCE, EMBED_SCOPE, EmbedJwtService
from auth.sessao_service import SessaoService
from auth.tenants_repo import SqliteTenantsRepo


GRAFICOS_PERMITIDOS = ("eventos_por_minuto",)


def _criar_app(tenants, users, svc, embed_svc, influx_mock):
    import os as _os

    from flask import Flask

    from auth import cliente_routes as cliente_mod
    from embed_routes import configurar as configurar_embed
    from embed_routes import embed_bp

    app = Flask(__name__)
    app.testing = True

    cliente_mod._svc_instance = svc
    cliente_mod._tenants_repo = tenants
    cliente_mod._clientes_users_repo = users
    _os.environ["COOKIE_SECURE"] = "false"
    app.register_blueprint(cliente_mod.cliente_auth_bp)

    configurar_embed(
        embed_jwt_service=embed_svc,
        sessao_service=svc,
        tenants_repo=tenants,
        influx_service=influx_mock,
        graficos_permitidos=GRAFICOS_PERMITIDOS,
    )
    app.register_blueprint(embed_bp)
    return app


def _cadastrar_e_logar(client, *, email="dan@acme.com", senha="secret-123",
                       slug="acme", nome_site="ACME Corp"):
    """Helper: cria conta via /cliente/auth/cadastro e devolve (cookie, body)."""
    r = client.post(
        "/cliente/auth/cadastro",
        json={"email": email, "senha": senha, "nome_site": nome_site, "slug": slug},
    )
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    cookie = r.headers.get("Set-Cookie", "")
    return cookie, body["user"]


class EmbedTokenTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(self._tmp.name) / "tenants.db")
        keys_dir = str(Path(self._tmp.name) / "keys")
        self.tenants = SqliteTenantsRepo(db_path)
        self.users = SqliteClientesUsersRepo(db_path)
        self.svc = SessaoService(self.users, sessao_ttl_segundos=3600)
        self.embed_svc = EmbedJwtService(keys_dir=keys_dir)
        self.influx = MagicMock()
        self.app = _criar_app(self.tenants, self.users, self.svc,
                              self.embed_svc, self.influx)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    # ---------- POST /embed/token ----------

    def test_token_sem_cookie_retorna_401(self):
        r = self.client.post("/embed/token", json={
            "site_id": "qualquer", "grafico_id": "eventos_por_minuto",
        })
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["code"], "NAO_AUTENTICADO")

    def test_token_payload_incompleto_retorna_400(self):
        _cadastrar_e_logar(self.client)
        for falta in ("site_id", "grafico_id"):
            payload = {"site_id": "x", "grafico_id": "eventos_por_minuto"}
            payload.pop(falta)
            r = self.client.post("/embed/token", json=payload)
            self.assertEqual(r.status_code, 400, f"campo {falta} ausente nao 400")

    def test_token_grafico_fora_da_allowlist_retorna_400(self):
        _cookie, user = _cadastrar_e_logar(self.client)
        r = self.client.post("/embed/token", json={
            "site_id": user["site_id"], "grafico_id": "../etc/passwd",
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "GRAFICO_INVALIDO")

    def test_token_site_id_de_outro_user_retorna_403(self):
        # User A
        _cadastrar_e_logar(self.client, email="a@x.com", slug="aaa", nome_site="AAA")
        site_a = self.tenants.obter_site_por_slug("aaa")
        # User B faz cadastro - cookie do B sobrescreve no client
        with self.app.test_client() as client_b:
            _cadastrar_e_logar(client_b, email="b@x.com", slug="bbb", nome_site="BBB")
            r = client_b.post("/embed/token", json={
                "site_id": site_a.id, "grafico_id": "eventos_por_minuto",
            })
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.get_json()["code"], "SITE_NEGADO")

    def test_token_happy_path_retorna_jwt_com_claims_corretas(self):
        _cookie, user = _cadastrar_e_logar(self.client)
        r = self.client.post("/embed/token", json={
            "site_id": user["site_id"], "grafico_id": "eventos_por_minuto",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        self.assertIn("token", body)
        self.assertIn("expira_em", body)

        decoded = pyjwt.decode(
            body["token"], self.embed_svc.public_pem(),
            algorithms=["RS256"], audience=EMBED_AUDIENCE,
        )
        self.assertEqual(decoded["scope"], EMBED_SCOPE)
        self.assertEqual(decoded["site_id"], user["site_id"])
        self.assertEqual(decoded["grafico_id"], "eventos_por_minuto")
        self.assertEqual(decoded["user_id"], user["id"])
        self.assertEqual(decoded["aud"], EMBED_AUDIENCE)
        self.assertEqual(decoded["iss"], "dsplayground.com.br")

    def test_token_ttl_clampeado_no_minimo(self):
        _cookie, user = _cadastrar_e_logar(self.client)
        r = self.client.post("/embed/token", json={
            "site_id": user["site_id"], "grafico_id": "eventos_por_minuto",
            "ttl_segundos": 5,
        })
        self.assertEqual(r.status_code, 200)
        decoded = pyjwt.decode(
            r.get_json()["token"], self.embed_svc.public_pem(),
            algorithms=["RS256"], audience=EMBED_AUDIENCE,
        )
        self.assertGreaterEqual(decoded["exp"] - decoded["iat"], 60)

    def test_token_ttl_clampeado_no_maximo(self):
        _cookie, user = _cadastrar_e_logar(self.client)
        r = self.client.post("/embed/token", json={
            "site_id": user["site_id"], "grafico_id": "eventos_por_minuto",
            "ttl_segundos": 999999,
        })
        self.assertEqual(r.status_code, 200)
        decoded = pyjwt.decode(
            r.get_json()["token"], self.embed_svc.public_pem(),
            algorithms=["RS256"], audience=EMBED_AUDIENCE,
        )
        self.assertLessEqual(decoded["exp"] - decoded["iat"], 600)


class EmbedDadosTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(self._tmp.name) / "tenants.db")
        keys_dir = str(Path(self._tmp.name) / "keys")
        self.tenants = SqliteTenantsRepo(db_path)
        self.users = SqliteClientesUsersRepo(db_path)
        self.svc = SessaoService(self.users, sessao_ttl_segundos=3600)
        self.embed_svc = EmbedJwtService(keys_dir=keys_dir)
        self.influx = MagicMock()
        self.influx.query_metricas_agregadas.return_value = [
            {"page_type": "home", "totais": {"visualizacoes": 42}},
        ]
        self.app = _criar_app(self.tenants, self.users, self.svc,
                              self.embed_svc, self.influx)
        self.client = self.app.test_client()
        # cria conta + emite token
        _cookie, self.user = _cadastrar_e_logar(self.client)
        r = self.client.post("/embed/token", json={
            "site_id": self.user["site_id"],
            "grafico_id": "eventos_por_minuto",
        })
        self.token = r.get_json()["token"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_dados_sem_authorization_retorna_401(self):
        r = self.client.get(f"/embed/dados/{self.user['site_id']}/eventos_por_minuto")
        self.assertEqual(r.status_code, 401)

    def test_dados_jwt_invalido_retorna_401(self):
        r = self.client.get(
            f"/embed/dados/{self.user['site_id']}/eventos_por_minuto",
            headers={"Authorization": "Bearer nao-eh-jwt"},
        )
        self.assertEqual(r.status_code, 401)

    def test_dados_jwt_com_aud_errado_retorna_401(self):
        # Forja JWT assinado com a chave do embed mas aud="outro"
        import jwt as _pyjwt
        from datetime import datetime, timedelta, timezone
        agora = datetime.now(timezone.utc)
        payload = {
            "iss": "dsplayground.com.br",
            "aud": "outro.example.com",
            "scope": EMBED_SCOPE,
            "site_id": self.user["site_id"],
            "grafico_id": "eventos_por_minuto",
            "user_id": self.user["id"],
            "iat": int(agora.timestamp()),
            "exp": int((agora + timedelta(minutes=5)).timestamp()),
        }
        token_ruim = _pyjwt.encode(
            payload, self.embed_svc._private_pem, algorithm="RS256",
        )
        r = self.client.get(
            f"/embed/dados/{self.user['site_id']}/eventos_por_minuto",
            headers={"Authorization": f"Bearer {token_ruim}"},
        )
        self.assertEqual(r.status_code, 401)

    def test_dados_path_divergente_do_claim_retorna_403(self):
        # Token foi emitido pra eventos_por_minuto, mas path pede outro grafico
        r = self.client.get(
            f"/embed/dados/{self.user['site_id']}/grafico_diferente",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(r.status_code, 403)

    def test_dados_happy_path_retorna_serie(self):
        r = self.client.get(
            f"/embed/dados/{self.user['site_id']}/eventos_por_minuto",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        self.assertEqual(body["site_id"], self.user["site_id"])
        self.assertEqual(body["grafico_id"], "eventos_por_minuto")
        self.assertIn("pontos", body)
        # Influx mock retornou [{"page_type":"home","totais":{"visualizacoes":42}}]
        self.assertEqual(body["pontos"][0]["totais"]["visualizacoes"], 42)


if __name__ == "__main__":
    unittest.main()
