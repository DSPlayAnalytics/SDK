"""Testes da camada de auth do dashboard (clientes_users + sessao + magic-link).

Cobre:
  - ClientesUsersRepo: CRUD de users, sessoes, magic-links (SQLite)
  - SessaoService: criacao de user, autenticacao por senha, ciclo de vida
    da sessao (criar, validar, revogar, expirar), fluxo magic-link completo,
    rate-limit por user e por IP.

Nao cobre Postgres (mesma interface — validacao futura via teste-ambiente-B).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.clientes_users_repo import (
    SqliteClientesUsersRepo,
    hash_token,
    normalizar_email,
)
from auth.sessao_service import (
    RateLimitExcedido,
    SessaoService,
    TOKEN_BYTES,
)
from auth.tenants_repo import SqliteTenantsRepo


# ----------------------------------------------------------------------
# Fixture helpers
# ----------------------------------------------------------------------


def _preparar_db(tmpdir: Path) -> tuple[SqliteTenantsRepo, SqliteClientesUsersRepo, str]:
    """Cria ambos os repos no mesmo arquivo sqlite + 1 site de teste.
    Retorna (tenants, clientes_users, site_id)."""
    db_path = str(tmpdir / "tenants.db")
    tenants = SqliteTenantsRepo(db_path)
    users = SqliteClientesUsersRepo(db_path)
    site = tenants.criar_site(
        slug="acme", nome="ACME Corp",
        ambiente="development", dominios=["https://acme.test"],
    )
    return tenants, users, site.id


# ----------------------------------------------------------------------
# Repo tests
# ----------------------------------------------------------------------


class ClientesUsersRepoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        _, self.repo, self.site_id = _preparar_db(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    # --- users

    def test_criar_user_normaliza_email_para_lowercase(self):
        u = self.repo.criar_user(self.site_id, "Foo@Bar.COM")
        self.assertEqual(u.email, "foo@bar.com")
        self.assertEqual(u.papel, "viewer")
        self.assertTrue(u.ativo)
        self.assertIsNone(u.ultimo_login)

    def test_obter_user_por_email_e_case_insensitive(self):
        criado = self.repo.criar_user(self.site_id, "dan@example.com")
        achado = self.repo.obter_user_por_email("DAN@EXAMPLE.COM")
        self.assertIsNotNone(achado)
        self.assertEqual(achado.id, criado.id)

    def test_registrar_login_atualiza_ultimo_login(self):
        u = self.repo.criar_user(self.site_id, "x@y.com")
        self.repo.registrar_login(u.id)
        achado = self.repo.obter_user(u.id)
        self.assertIsNotNone(achado.ultimo_login)

    def test_desativar_user_impede_posterior_ativo(self):
        u = self.repo.criar_user(self.site_id, "x@y.com")
        self.repo.desativar_user(u.id)
        achado = self.repo.obter_user(u.id)
        self.assertFalse(achado.ativo)

    def test_email_duplicado_lanca_excecao(self):
        self.repo.criar_user(self.site_id, "dup@x.com")
        with self.assertRaises(Exception):
            self.repo.criar_user(self.site_id, "DUP@x.com")

    # --- sessoes

    def test_criar_sessao_e_recuperar_por_hash(self):
        u = self.repo.criar_user(self.site_id, "a@b.com")
        exp = datetime.now(timezone.utc) + timedelta(hours=1)
        s = self.repo.criar_sessao(u.id, "h1", expira_em=exp, ip="127.0.0.1", user_agent="UA")
        achada = self.repo.obter_sessao_por_hash("h1")
        self.assertEqual(achada.user_id, u.id)
        self.assertEqual(achada.ip, "127.0.0.1")
        self.assertIsNone(achada.revogada_em)

    def test_revogar_sessao_marca_revogada_em(self):
        u = self.repo.criar_user(self.site_id, "a@b.com")
        exp = datetime.now(timezone.utc) + timedelta(hours=1)
        self.repo.criar_sessao(u.id, "h2", expira_em=exp)
        self.repo.revogar_sessao("h2")
        achada = self.repo.obter_sessao_por_hash("h2")
        self.assertIsNotNone(achada.revogada_em)

    def test_limpar_sessoes_expiradas_remove_expiradas_e_revogadas(self):
        u = self.repo.criar_user(self.site_id, "a@b.com")
        passado = datetime.now(timezone.utc) - timedelta(seconds=1)
        futuro = datetime.now(timezone.utc) + timedelta(hours=1)
        self.repo.criar_sessao(u.id, "expirada", expira_em=passado)
        self.repo.criar_sessao(u.id, "ativa", expira_em=futuro)
        self.repo.criar_sessao(u.id, "revogada", expira_em=futuro)
        self.repo.revogar_sessao("revogada")

        removidas = self.repo.limpar_sessoes_expiradas()
        self.assertEqual(removidas, 2)
        self.assertIsNone(self.repo.obter_sessao_por_hash("expirada"))
        self.assertIsNone(self.repo.obter_sessao_por_hash("revogada"))
        self.assertIsNotNone(self.repo.obter_sessao_por_hash("ativa"))

    # --- magic-links

    def test_consumir_magic_link_ok_e_idempotente(self):
        u = self.repo.criar_user(self.site_id, "a@b.com")
        exp = datetime.now(timezone.utc) + timedelta(minutes=15)
        self.repo.criar_magic_link(u.id, "mh1", expira_em=exp)

        self.assertTrue(self.repo.consumir_magic_link("mh1"))
        # 2a vez NAO consome mais (ja marcou consumido_em)
        self.assertFalse(self.repo.consumir_magic_link("mh1"))

    def test_consumir_magic_link_expirado_retorna_false(self):
        u = self.repo.criar_user(self.site_id, "a@b.com")
        passado = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.repo.criar_magic_link(u.id, "exp", expira_em=passado)
        self.assertFalse(self.repo.consumir_magic_link("exp"))

    def test_contar_magic_links_recentes_por_user(self):
        u = self.repo.criar_user(self.site_id, "a@b.com")
        exp = datetime.now(timezone.utc) + timedelta(minutes=15)
        for i in range(3):
            self.repo.criar_magic_link(u.id, f"ml{i}", expira_em=exp)
        self.assertEqual(self.repo.contar_magic_links_recentes(u.id, 60), 3)
        self.assertEqual(self.repo.contar_magic_links_recentes("outro", 60), 0)

    def test_contar_magic_links_por_ip(self):
        u = self.repo.criar_user(self.site_id, "a@b.com")
        exp = datetime.now(timezone.utc) + timedelta(minutes=15)
        for i in range(2):
            self.repo.criar_magic_link(u.id, f"x{i}", expira_em=exp, ip="1.2.3.4")
        self.repo.criar_magic_link(u.id, "outro", expira_em=exp, ip="9.9.9.9")
        self.assertEqual(self.repo.contar_magic_links_por_ip("1.2.3.4", 60), 2)
        self.assertEqual(self.repo.contar_magic_links_por_ip("9.9.9.9", 60), 1)


# ----------------------------------------------------------------------
# SessaoService tests
# ----------------------------------------------------------------------


class SessaoServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        _, self.repo, self.site_id = _preparar_db(Path(self._tmp.name))
        self.svc = SessaoService(
            self.repo,
            sessao_ttl_segundos=3600,
            magic_link_ttl_segundos=900,
            max_magic_links_por_user=3,
            max_magic_links_por_ip=5,
            janela_rate_limit_segundos=60,
        )

    def tearDown(self):
        self._tmp.cleanup()

    # --- criar_user + autenticar_por_senha

    def test_criar_user_sem_senha_nao_autentica(self):
        self.svc.criar_user(self.site_id, "x@y.com")
        self.assertIsNone(self.svc.autenticar_por_senha("x@y.com", "qualquer"))

    def test_criar_user_com_senha_autentica_e_rejeita_senha_errada(self):
        self.svc.criar_user(self.site_id, "x@y.com", senha="secreta-123")
        self.assertIsNotNone(self.svc.autenticar_por_senha("x@y.com", "secreta-123"))
        self.assertIsNone(self.svc.autenticar_por_senha("x@y.com", "errada"))

    def test_autenticar_com_user_desativado_falha(self):
        u = self.svc.criar_user(self.site_id, "x@y.com", senha="ok")
        self.repo.desativar_user(u.id)
        self.assertIsNone(self.svc.autenticar_por_senha("x@y.com", "ok"))

    def test_autenticar_registra_ultimo_login(self):
        u = self.svc.criar_user(self.site_id, "x@y.com", senha="ok")
        antes = self.repo.obter_user(u.id).ultimo_login
        self.svc.autenticar_por_senha("x@y.com", "ok")
        depois = self.repo.obter_user(u.id).ultimo_login
        self.assertIsNone(antes)
        self.assertIsNotNone(depois)

    # --- sessao

    def test_criar_sessao_retorna_plaintext_e_persiste_so_hash(self):
        u = self.svc.criar_user(self.site_id, "x@y.com")
        criada = self.svc.criar_sessao(u.id, ip="127.0.0.1", user_agent="UA")
        self.assertTrue(criada.cookie_plaintext)
        # plaintext NUNCA persiste
        persistida = self.repo.obter_sessao_por_hash(hash_token(criada.cookie_plaintext))
        self.assertIsNotNone(persistida)
        self.assertEqual(persistida.token_hash, hash_token(criada.cookie_plaintext))
        self.assertNotEqual(persistida.token_hash, criada.cookie_plaintext)

    def test_validar_cookie_retorna_user_quando_sessao_ativa(self):
        u = self.svc.criar_user(self.site_id, "x@y.com")
        criada = self.svc.criar_sessao(u.id)
        achado = self.svc.validar_cookie(criada.cookie_plaintext)
        self.assertIsNotNone(achado)
        self.assertEqual(achado.id, u.id)

    def test_validar_cookie_invalido_retorna_none(self):
        self.assertIsNone(self.svc.validar_cookie("nao-existe"))
        self.assertIsNone(self.svc.validar_cookie(""))
        self.assertIsNone(self.svc.validar_cookie(None))  # type: ignore[arg-type]

    def test_validar_cookie_sessao_revogada_retorna_none(self):
        u = self.svc.criar_user(self.site_id, "x@y.com")
        criada = self.svc.criar_sessao(u.id)
        self.svc.revogar_sessao(criada.cookie_plaintext)
        self.assertIsNone(self.svc.validar_cookie(criada.cookie_plaintext))

    def test_validar_cookie_sessao_expirada_retorna_none(self):
        u = self.svc.criar_user(self.site_id, "x@y.com")
        # TTL minusculo para expirar rapido
        svc_curto = SessaoService(self.repo, sessao_ttl_segundos=1)
        criada = svc_curto.criar_sessao(u.id)
        time.sleep(1.2)
        self.assertIsNone(svc_curto.validar_cookie(criada.cookie_plaintext))

    def test_validar_cookie_com_user_desativado_retorna_none(self):
        u = self.svc.criar_user(self.site_id, "x@y.com")
        criada = self.svc.criar_sessao(u.id)
        self.repo.desativar_user(u.id)
        self.assertIsNone(self.svc.validar_cookie(criada.cookie_plaintext))

    def test_cookie_plaintext_tem_entropia_suficiente(self):
        u = self.svc.criar_user(self.site_id, "x@y.com")
        cookies = {self.svc.criar_sessao(u.id).cookie_plaintext for _ in range(50)}
        self.assertEqual(len(cookies), 50)  # todos unicos
        for c in cookies:
            # token_urlsafe(32) gera ~43 chars base64url
            self.assertGreaterEqual(len(c), 40)

    # --- magic-link

    def test_solicitar_magic_link_com_email_inexistente_retorna_none(self):
        # nao levanta — nao vaza existencia
        self.assertIsNone(self.svc.solicitar_magic_link("nao-existe@x.com"))

    def test_solicitar_magic_link_ok(self):
        self.svc.criar_user(self.site_id, "x@y.com")
        criado = self.svc.solicitar_magic_link("x@y.com", ip="1.1.1.1")
        self.assertIsNotNone(criado)
        self.assertTrue(criado.token_plaintext)
        self.assertEqual(criado.magic_link.user_id,
                         self.repo.obter_user_por_email("x@y.com").id)

    def test_consumir_magic_link_cria_sessao(self):
        self.svc.criar_user(self.site_id, "x@y.com")
        mc = self.svc.solicitar_magic_link("x@y.com")
        self.assertIsNotNone(mc)
        sessao = self.svc.consumir_magic_link(mc.token_plaintext, ip="2.2.2.2")
        self.assertIsNotNone(sessao)
        # cookie e imediatamente valido
        user = self.svc.validar_cookie(sessao.cookie_plaintext)
        self.assertIsNotNone(user)

    def test_consumir_magic_link_ja_consumido_falha(self):
        self.svc.criar_user(self.site_id, "x@y.com")
        mc = self.svc.solicitar_magic_link("x@y.com")
        self.svc.consumir_magic_link(mc.token_plaintext)
        self.assertIsNone(self.svc.consumir_magic_link(mc.token_plaintext))

    def test_consumir_magic_link_invalido_falha(self):
        self.assertIsNone(self.svc.consumir_magic_link("nao-existe"))
        self.assertIsNone(self.svc.consumir_magic_link(""))

    def test_rate_limit_por_user_estoura(self):
        self.svc.criar_user(self.site_id, "x@y.com")
        for _ in range(3):
            self.svc.solicitar_magic_link("x@y.com", ip="1.1.1.1")
        with self.assertRaises(RateLimitExcedido):
            self.svc.solicitar_magic_link("x@y.com", ip="1.1.1.1")

    def test_rate_limit_por_ip_estoura(self):
        # 5 users diferentes, mesmo IP — para nao bater limite-por-user (3)
        for i in range(6):
            self.svc.criar_user(self.site_id, f"u{i}@y.com")
        # 5 primeiros sao ok
        for i in range(5):
            self.svc.solicitar_magic_link(f"u{i}@y.com", ip="9.9.9.9")
        # 6o estoura limite por IP
        with self.assertRaises(RateLimitExcedido):
            self.svc.solicitar_magic_link("u5@y.com", ip="9.9.9.9")



# ----------------------------------------------------------------------
# Flask blueprint tests
# ----------------------------------------------------------------------


class _EmailRecorder:
    """Capta emails enviados em vez de disparar de verdade."""
    def __init__(self):
        self.enviados: list[dict] = []

    def enviar(self, *, destinatario, assunto, corpo_texto, corpo_html=None):
        self.enviados.append({
            "para": destinatario, "assunto": assunto, "texto": corpo_texto,
        })
        return True


def _criar_app_cliente(repo, svc, sender):
    import os as _os
    from flask import Flask
    from auth import cliente_routes as mod

    app = Flask(__name__)
    mod._svc_instance = svc
    mod._email_sender = sender
    _os.environ["COOKIE_SECURE"] = "false"  # permite teste sem https
    app.register_blueprint(mod.cliente_auth_bp)
    app.testing = True
    return app


class ClienteAuthEndpointsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        _, self.repo, self.site_id = _preparar_db(Path(self._tmp.name))
        self.svc = SessaoService(self.repo, sessao_ttl_segundos=3600,
                                  magic_link_ttl_segundos=900)
        self.sender = _EmailRecorder()
        self.app = _criar_app_cliente(self.repo, self.svc, self.sender)
        self.client = self.app.test_client()
        # user padrao com senha para /login
        self.svc.criar_user(self.site_id, "dan@acme.com", senha="secret-123", papel="admin")

    def tearDown(self):
        self._tmp.cleanup()

    # /login
    def test_login_ok_seta_cookie(self):
        r = self.client.post("/cliente/auth/login",
                             json={"email": "dan@acme.com", "senha": "secret-123"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("cliente_session", r.headers.get("Set-Cookie", ""))

    def test_login_credenciais_invalidas_retorna_401(self):
        r = self.client.post("/cliente/auth/login",
                             json={"email": "dan@acme.com", "senha": "errada"})
        self.assertEqual(r.status_code, 401)

    def test_login_sem_payload_retorna_400(self):
        r = self.client.post("/cliente/auth/login", json={})
        self.assertEqual(r.status_code, 400)

    # /me
    def test_me_sem_cookie_retorna_401(self):
        r = self.client.get("/cliente/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_me_com_cookie_valido_retorna_user(self):
        self.client.post("/cliente/auth/login",
                         json={"email": "dan@acme.com", "senha": "secret-123"})
        r = self.client.get("/cliente/auth/me")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["email"], "dan@acme.com")
        self.assertEqual(body["site_id"], self.site_id)
        self.assertEqual(body["papel"], "admin")

    # /gate
    def test_gate_sem_cookie_retorna_401(self):
        r = self.client.get("/cliente/auth/gate")
        self.assertEqual(r.status_code, 401)

    def test_gate_com_cookie_valido_retorna_header_webauth(self):
        self.client.post("/cliente/auth/login",
                         json={"email": "dan@acme.com", "senha": "secret-123"})
        r = self.client.get("/cliente/auth/gate")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-WEBAUTH-USER"), self.site_id)
        self.assertEqual(r.headers.get("X-WEBAUTH-PAPEL"), "admin")

    # /logout
    def test_logout_revoga_sessao_e_limpa_cookie(self):
        self.client.post("/cliente/auth/login",
                         json={"email": "dan@acme.com", "senha": "secret-123"})
        r = self.client.post("/cliente/auth/logout")
        self.assertEqual(r.status_code, 200)
        # apos logout, /me deve retornar 401
        r2 = self.client.get("/cliente/auth/me")
        self.assertEqual(r2.status_code, 401)

    # /magic-link/solicitar
    def test_magic_link_solicitar_email_existente_dispara_e_responde_200(self):
        r = self.client.post("/cliente/auth/magic-link/solicitar",
                             json={"email": "dan@acme.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sender.enviados), 1)
        self.assertEqual(self.sender.enviados[0]["para"], "dan@acme.com")
        # link contem ?t=
        self.assertIn("?t=", self.sender.enviados[0]["texto"])

    def test_magic_link_solicitar_email_fantasma_responde_200_mas_nao_envia(self):
        r = self.client.post("/cliente/auth/magic-link/solicitar",
                             json={"email": "nao-existe@x.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sender.enviados), 0)

    def test_magic_link_solicitar_rate_limit_retorna_429(self):
        svc_tight = SessaoService(self.repo, max_magic_links_por_user=1,
                                   janela_rate_limit_segundos=60)
        from auth import cliente_routes as mod
        mod._svc_instance = svc_tight

        for _ in range(1):
            self.client.post("/cliente/auth/magic-link/solicitar",
                             json={"email": "dan@acme.com"})
        r = self.client.post("/cliente/auth/magic-link/solicitar",
                             json={"email": "dan@acme.com"})
        self.assertEqual(r.status_code, 429)

        # restaurar svc para outros testes
        mod._svc_instance = self.svc

    # /magic-link/verificar
    def test_magic_link_verificar_ok_redireciona_e_seta_cookie(self):
        self.client.post("/cliente/auth/magic-link/solicitar",
                         json={"email": "dan@acme.com"})
        # extrair token do email capturado
        import re
        texto = self.sender.enviados[0]["texto"]
        m = re.search(r"t=([^&\s]+)", texto)
        self.assertIsNotNone(m)
        token = m.group(1)

        r = self.client.get(f"/cliente/auth/magic-link/verificar?t={token}")
        self.assertEqual(r.status_code, 302)
        self.assertIn("cliente_session", r.headers.get("Set-Cookie", ""))
        # apos verificar, /me deve dar 200
        r2 = self.client.get("/cliente/auth/me")
        self.assertEqual(r2.status_code, 200)

    def test_magic_link_verificar_token_invalido_retorna_400(self):
        r = self.client.get("/cliente/auth/magic-link/verificar?t=xxx-invalido")
        self.assertEqual(r.status_code, 400)

    def test_magic_link_verificar_sem_token_retorna_400(self):
        r = self.client.get("/cliente/auth/magic-link/verificar")
        self.assertEqual(r.status_code, 400)

    def test_magic_link_verificar_token_ja_consumido_falha(self):
        self.client.post("/cliente/auth/magic-link/solicitar",
                         json={"email": "dan@acme.com"})
        import re
        texto = self.sender.enviados[0]["texto"]
        token = re.search(r"t=([^&\s]+)", texto).group(1)
        # consome 1a vez
        self.client.get(f"/cliente/auth/magic-link/verificar?t={token}")
        # 2a vez falha
        r = self.client.get(f"/cliente/auth/magic-link/verificar?t={token}")
        self.assertEqual(r.status_code, 400)


class CookieDomainTests(unittest.TestCase):
    """COOKIE_DOMAIN env controla atributo Domain= no Set-Cookie.

    Sem isso, cookie e host-only — setado por api.X nao chega em app.X.
    Com Domain=dsplayground.com.br, cookie viaja entre subdominios same-site.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        _, self.repo, self.site_id = _preparar_db(Path(self._tmp.name))
        self.svc = SessaoService(self.repo, sessao_ttl_segundos=3600)
        self.sender = _EmailRecorder()
        self.svc.criar_user(self.site_id, "dan@acme.com", senha="secret-123", papel="admin")
        self._env_original = os.environ.get("COOKIE_DOMAIN")

    def tearDown(self):
        if self._env_original is None:
            os.environ.pop("COOKIE_DOMAIN", None)
        else:
            os.environ["COOKIE_DOMAIN"] = self._env_original
        self._tmp.cleanup()

    def _post_login(self):
        app = _criar_app_cliente(self.repo, self.svc, self.sender)
        client = app.test_client()
        return client.post("/cliente/auth/login",
                           json={"email": "dan@acme.com", "senha": "secret-123"})

    def test_set_cookie_sem_env_nao_inclui_domain(self):
        os.environ.pop("COOKIE_DOMAIN", None)
        r = self._post_login()
        self.assertEqual(r.status_code, 200)
        set_cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("cliente_session=", set_cookie)
        # Sem env -> sem atributo Domain (host-only, comportamento legado)
        self.assertNotIn("Domain=", set_cookie)

    def test_set_cookie_com_env_inclui_domain(self):
        os.environ["COOKIE_DOMAIN"] = "dsplayground.com.br"
        r = self._post_login()
        self.assertEqual(r.status_code, 200)
        set_cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("Domain=dsplayground.com.br", set_cookie)

    def test_clear_cookie_usa_mesmo_domain(self):
        """Logout precisa setar Domain igual pra browser limpar o cookie."""
        os.environ["COOKIE_DOMAIN"] = "dsplayground.com.br"
        app = _criar_app_cliente(self.repo, self.svc, self.sender)
        client = app.test_client()
        client.post("/cliente/auth/login",
                    json={"email": "dan@acme.com", "senha": "secret-123"})
        r = client.post("/cliente/auth/logout")
        self.assertEqual(r.status_code, 200)
        set_cookie = r.headers.get("Set-Cookie", "")
        # delete_cookie do Flask emite Set-Cookie com Max-Age=0 ou Expires no passado
        self.assertIn("cliente_session=", set_cookie)
        self.assertIn("Domain=dsplayground.com.br", set_cookie)

    def test_cadastro_tambem_usa_domain(self):
        """Cookie do /cadastro tambem precisa do Domain pra funcionar em app.X."""
        os.environ["COOKIE_DOMAIN"] = "dsplayground.com.br"
        from auth import cliente_routes as mod
        from auth.tenants_repo import SqliteTenantsRepo as TR
        from auth.clientes_users_repo import SqliteClientesUsersRepo as CR
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(tmp.name) / "tenants2.db")
        tenants = TR(db_path)
        users = CR(db_path)
        svc = SessaoService(users, sessao_ttl_segundos=3600)
        mod._svc_instance = svc
        mod._tenants_repo = tenants
        mod._clientes_users_repo = users
        # No-op no provisionamento pra nao tentar importar Postgres em test
        original_prov = mod._provisionar_pos_cadastro
        mod._provisionar_pos_cadastro = lambda **kw: None
        os.environ["COOKIE_SECURE"] = "false"

        try:
            from flask import Flask
            app = Flask(__name__)
            app.register_blueprint(mod.cliente_auth_bp)
            client = app.test_client()
            r = client.post("/cliente/auth/cadastro", json={
                "email": "novo@x.com", "senha": "secret-456",
                "nome_site": "Novo", "slug": "novo-cookie-domain",
            })
            self.assertEqual(r.status_code, 201)
            self.assertIn("Domain=dsplayground.com.br", r.headers.get("Set-Cookie", ""))
        finally:
            mod._provisionar_pos_cadastro = original_prov
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
