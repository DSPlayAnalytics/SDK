"""Blueprint `/cliente/auth` — auth humana do dashboard do cliente.

Endpoints:
  POST /cadastro                 — body {email,senha,nome_site,slug}; 201 + cookie
  POST /login                    — body {email, senha}, set cookie, 200/401
  POST /logout                   — revoga sessao, limpa cookie, 200
  GET  /me                       — retorna {user_id, site_id, papel} ou 401
  GET  /gate                     — nginx auth_request: 200 + X-WEBAUTH-USER=<site_id> ou 401
  POST /magic-link/solicitar     — body {email}; sempre 200 {ok:true} (nao vaza)
  GET  /magic-link/verificar?t=..— 302 → /cliente/metricas + Set-Cookie ou 400

Cookie:
  - Nome:  cliente_session
  - Flags: HttpOnly, Secure (env COOKIE_SECURE; default true), SameSite=Strict
  - Path:  /
  - Domain: env COOKIE_DOMAIN (default vazio = host-only). Em prod com
            landing/api/app em subdominios distintos do mesmo eTLD+1, setar
            COOKIE_DOMAIN=dsplayground.com.br pra cookie viajar entre eles.
  - TTL:   vem de SessaoService.sessao_ttl_segundos

Todos os eventos sao logados em `security` (CrowdSec parseia):
  `auth_cliente_login_ok|fail|logout|gate_ok|gate_negado|magic_solicitado|magic_consumido`

Referencia: ark/docs/dashboard-cliente.md (secoes 6, 8, 9, 10).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Optional
from urllib.parse import urlencode

from flask import Blueprint, current_app, g, jsonify, make_response, redirect, request

from .clientes_users_repo import ClientesUsersRepo
from .email_sender import EmailSender, criar_sender_padrao
from .grafana_sync import GrafanaSyncService
from .sessao_service import RateLimitExcedido, SessaoService
from .tenants_repo import TenantsRepo


_RE_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9\-]{1,30}[a-z0-9])$")
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SENHA_MIN = 8


logger = logging.getLogger("auth.cliente")
security_logger = logging.getLogger("security")


COOKIE_NAME = "cliente_session"


cliente_auth_bp = Blueprint("cliente_auth", __name__, url_prefix="/cliente/auth")


# ---------- singletons configuraveis em runtime ----------
# Espelha o padrao de jwt_service/tenants_repo: app de teste substitui estas
# variaveis diretamente antes de registrar o blueprint.

_svc_instance: Optional[SessaoService] = None
_email_sender: Optional[EmailSender] = None
_grafana_sync: Optional[GrafanaSyncService] = None
_tenants_repo: Optional[TenantsRepo] = None
_clientes_users_repo: Optional[ClientesUsersRepo] = None


def configurar(
    svc: SessaoService,
    email_sender: Optional[EmailSender] = None,
    grafana_sync: Optional[GrafanaSyncService] = None,
    tenants_repo: Optional[TenantsRepo] = None,
    clientes_users_repo: Optional[ClientesUsersRepo] = None,
) -> None:
    """Configura singletons. Chamar uma vez no boot.

    `grafana_sync` e `tenants_repo` sao opcionais; quando ambos estao
    presentes, /gate sincroniza membership da org Grafana do cliente
    (sec 13 do dashboard-cliente.md). Sem eles, /gate so valida cookie.

    `tenants_repo` e `clientes_users_repo` sao obrigatorios para /cadastro.
    """
    global _svc_instance, _email_sender, _grafana_sync, _tenants_repo
    global _clientes_users_repo
    _svc_instance = svc
    _email_sender = email_sender or criar_sender_padrao()
    _grafana_sync = grafana_sync
    _tenants_repo = tenants_repo
    _clientes_users_repo = clientes_users_repo


def _obter_svc() -> SessaoService:
    if _svc_instance is None:
        raise RuntimeError("cliente_auth nao configurado — chamar configurar() antes do app.run")
    return _svc_instance


def _obter_email_sender() -> EmailSender:
    global _email_sender
    if _email_sender is None:
        _email_sender = criar_sender_padrao()
    return _email_sender


def _ip_cliente() -> Optional[str]:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.environ.get("REMOTE_ADDR")


def _cookie_domain() -> Optional[str]:
    """Devolve o atributo Domain= do cookie ou None (host-only).

    Necessario quando landing/api/dashboard ficam em subdominios diferentes
    do mesmo eTLD+1 (ex: api.X seta cookie pra app.X ler). Sem env definida,
    cookie continua host-only (comportamento legado em apex unico).
    """
    valor = os.environ.get("COOKIE_DOMAIN", "").strip()
    return valor or None


def _set_cookie(response, cookie_plaintext: str, *, max_age: int) -> None:
    secure = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
    response.set_cookie(
        COOKIE_NAME, cookie_plaintext,
        max_age=max_age, httponly=True, secure=secure, samesite="Strict",
        path="/", domain=_cookie_domain(),
    )


def _clear_cookie(response) -> None:
    # delete_cookie precisa do mesmo Domain= que foi setado, senao o browser
    # nao limpa (atributos diferentes = cookies diferentes).
    response.delete_cookie(COOKIE_NAME, path="/", domain=_cookie_domain())


def _erro(code: str, message: str, status: int):
    return jsonify({"status": "error", "code": code, "message": message}), status


def _provisionar_pos_cadastro(*, slug: str, nome: str, plano: str,
                              ambiente: str, site_id: str) -> None:
    """Dispara provisionamento idempotente em background (best-effort).

    Cria bucket Influx + token + org Grafana + datasource + dashboards.
    Falhas sao logadas em security_logger; cadastro NAO falha por causa disso
    (admin pode reconciliar com `python scripts/provisionar_cliente.py --slug X`).

    Esta funcao e o ponto de hook substituido em testes (sincrono, capturando
    chamadas). Em producao spawna `_executar_provisionamento` em thread daemon.
    """
    import threading
    threading.Thread(
        target=_executar_provisionamento,
        kwargs={
            "slug": slug, "nome": nome, "plano": plano,
            "ambiente": ambiente, "site_id": site_id,
        },
        daemon=True,
        name=f"provisionar-{slug}",
    ).start()


def _executar_provisionamento(*, slug: str, nome: str, plano: str,
                              ambiente: str, site_id: str) -> None:
    """Execucao real do provisionamento — chamado em thread daemon.

    Constroi argparse.Namespace artificial pra reaproveitar `provisionar()`
    do scripts/provisionar_cliente.py sem refactor. Logs estruturados pro
    CrowdSec parsear.
    """
    import argparse
    try:
        from scripts.provisionar_cliente import provisionar
    except Exception as erro:  # noqa: BLE001
        security_logger.error(
            "evento=provisionamento_import_falhou site_id=%s slug=%s motivo=%s",
            site_id, slug, erro,
        )
        return

    args = argparse.Namespace(
        slug=slug, nome=nome, ambiente=ambiente,
        plano=plano, dominio=[], bucket=None, skip_dashboards=False,
    )
    try:
        result = provisionar(args)
        security_logger.info(
            "evento=provisionamento_ok site_id=%s slug=%s bucket=%s grafana_org=%s",
            site_id, slug, result.bucket_name, result.grafana_org_id,
        )
    except SystemExit as erro:
        security_logger.error(
            "evento=provisionamento_falhou site_id=%s slug=%s motivo=%s",
            site_id, slug, erro,
        )
    except Exception as erro:  # noqa: BLE001
        security_logger.exception(
            "evento=provisionamento_excecao site_id=%s slug=%s motivo=%s",
            site_id, slug, erro,
        )


# ---------- endpoints ----------


@cliente_auth_bp.route("/cadastro", methods=["POST"])
def cadastro():
    """Cria site novo + admin user + auto-login.

    Payload: {email, senha, nome_site, slug}
    - slug: 3-32 chars, [a-z0-9-], comeca/termina com alfanum (constraint Influx-friendly)
    - bucket_name fixado em `cliente_<slug>` (bucket-per-cliente)
    - papel do user inicial: admin
    - retorna 201 + cookie cliente_session pra auto-login
    """
    if _tenants_repo is None or _clientes_users_repo is None:
        return _erro("CADASTRO_NAO_CONFIGURADO",
                     "tenants_repo/clientes_users_repo nao configurados", 503)

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    senha = body.get("senha") or ""
    nome_site = (body.get("nome_site") or "").strip()
    slug = (body.get("slug") or "").strip().lower()

    if not email or not senha or not nome_site or not slug:
        return _erro("PAYLOAD_INCOMPLETO",
                     "email, senha, nome_site e slug sao obrigatorios", 400)
    if not _RE_EMAIL.match(email):
        return _erro("EMAIL_INVALIDO", "formato de email invalido", 400)
    if len(senha) < _SENHA_MIN:
        return _erro("SENHA_CURTA", f"senha precisa ter ao menos {_SENHA_MIN} caracteres", 400)
    if not _RE_SLUG.match(slug):
        return _erro("SLUG_INVALIDO",
                     "slug deve ter 3-32 chars [a-z0-9-]; comecar/terminar com alfanum", 400)

    if _clientes_users_repo.obter_user_por_email(email) is not None:
        return _erro("EMAIL_JA_CADASTRADO", "email ja existe", 409)
    if _tenants_repo.obter_site_por_slug(slug) is not None:
        return _erro("SLUG_JA_CADASTRADO", "slug ja existe", 409)

    bucket_name = f"cliente_{slug}"
    try:
        site = _tenants_repo.criar_site(
            slug=slug, nome=nome_site,
            ambiente=os.environ.get("AMBIENTE", "production"),
            dominios=[], plano="free", bucket_name=bucket_name,
        )
    except sqlite3.IntegrityError:
        # corrida: outro cadastro pegou o slug entre o check e o insert
        return _erro("SLUG_JA_CADASTRADO", "slug ja existe", 409)

    svc = _obter_svc()
    user = svc.criar_user(site.id, email, senha=senha, papel="admin")
    criada = svc.criar_sessao(user.id, ip=_ip_cliente(),
                              user_agent=request.headers.get("User-Agent"))
    security_logger.info(
        "evento=auth_cliente_cadastro_ok site_id=%s slug=%s user_id=%s ip=%s",
        site.id, slug, user.id, _ip_cliente(),
    )

    # Best-effort: dispara provisionamento (bucket Influx + Grafana org +
    # datasource + dashboards) em thread daemon. Cadastro NAO falha se isso
    # quebrar — admin reconcilia com `provisionar_cliente.py --slug X` via cron.
    try:
        _provisionar_pos_cadastro(
            slug=slug, nome=nome_site, plano="free",
            ambiente=os.environ.get("AMBIENTE", "production"),
            site_id=site.id,
        )
    except Exception as erro:  # noqa: BLE001
        security_logger.error(
            "evento=provisionamento_dispatch_falhou site_id=%s slug=%s motivo=%s",
            site.id, slug, erro,
        )

    # Best-effort: email de boas-vindas (nao bloqueia response nem cadastro).
    try:
        _obter_email_sender().enviar(
            destinatario=user.email,
            assunto=f"Bem-vindo ao dsplayground! Seu site \"{nome_site}\" foi criado",
            corpo_texto=(
                f"Olá!\n\n"
                f"Seu site \"{nome_site}\" foi criado com sucesso no dsplayground.\n\n"
                f"Estamos configurando seu dashboard de métricas agora. Em alguns instantes "
                f"você poderá acessar em:\n"
                f"  https://app.dsplayground.com.br/cliente/metricas\n\n"
                f"Próximo passo — instalar o SDK:\n"
                f"  1. Copie sua publishable key em "
                f"https://dsplayground.com.br/cliente/configuracoes#chaves\n"
                f"  2. Adicione o snippet ao seu site\n\n"
                f"Dúvidas? Responda este e-mail.\n\n"
                f"—\nEquipe dsplayground\nhttps://dsplayground.com.br"
            ),
        )
    except Exception as erro_email:  # noqa: BLE001
        security_logger.error(
            "evento=email_boasvindas_falhou site_id=%s motivo=%s",
            site.id, erro_email,
        )

    resp = make_response(jsonify({
        "status": "success",
        "user": {"id": user.id, "site_id": user.site_id,
                 "email": user.email, "papel": user.papel},
        "site": {"id": site.id, "slug": site.slug, "nome": site.nome,
                 "bucket_name": site.bucket_name, "plano": site.plano},
    }), 201)
    _set_cookie(resp, criada.cookie_plaintext, max_age=svc._sessao_ttl)  # noqa: SLF001
    return resp


@cliente_auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    senha = body.get("senha") or ""
    if not email or not senha:
        return _erro("CREDENCIAIS_INVALIDAS", "email e senha obrigatorios", 400)

    svc = _obter_svc()
    user = svc.autenticar_por_senha(email, senha)
    ip = _ip_cliente()
    ua = request.headers.get("User-Agent")

    if user is None:
        security_logger.info(
            "evento=auth_cliente_login_fail email=%s ip=%s ua=%r",
            email, ip, ua,
        )
        return _erro("CREDENCIAIS_INVALIDAS", "email ou senha incorretos", 401)

    criada = svc.criar_sessao(user.id, ip=ip, user_agent=ua)
    security_logger.info(
        "evento=auth_cliente_login_ok site_id=%s user_id=%s ip=%s",
        user.site_id, user.id, ip,
    )

    resp = make_response(jsonify({
        "status": "success",
        "user": {"id": user.id, "site_id": user.site_id, "email": user.email, "papel": user.papel},
    }))
    _set_cookie(resp, criada.cookie_plaintext, max_age=svc._sessao_ttl)  # noqa: SLF001
    return resp


@cliente_auth_bp.route("/logout", methods=["POST"])
def logout():
    cookie = request.cookies.get(COOKIE_NAME, "")
    if cookie:
        _obter_svc().revogar_sessao(cookie)
        security_logger.info("evento=auth_cliente_logout ip=%s", _ip_cliente())
    resp = make_response(jsonify({"status": "success"}))
    _clear_cookie(resp)
    return resp


@cliente_auth_bp.route("/me", methods=["GET"])
def me():
    cookie = request.cookies.get(COOKIE_NAME, "")
    user = _obter_svc().validar_cookie(cookie)
    if user is None:
        return _erro("NAO_AUTENTICADO", "sessao ausente ou invalida", 401)
    return jsonify({
        "user_id": user.id, "site_id": user.site_id,
        "email": user.email, "papel": user.papel,
    })


def _ambiente_de_pk(valor: str) -> str:
    """`pk_production_xxx` -> `production`. Defensivo pra valores legados."""
    partes = valor.split("_", 2)
    return partes[1] if len(partes) >= 3 and partes[0] == "pk" else "unknown"


@cliente_auth_bp.route("/senha", methods=["PATCH"])
def alterar_senha():
    """Troca senha do user logado. Body: {senha_atual, nova_senha}.
    Codigos: SENHA_INVALIDA (403), SENHA_CURTA (400), NAO_AUTENTICADO (401).
    """
    cookie = request.cookies.get(COOKIE_NAME, "")
    user = _obter_svc().validar_cookie(cookie)
    if user is None:
        return _erro("NAO_AUTENTICADO", "sessao ausente ou invalida", 401)
    body = request.get_json(silent=True) or {}
    senha_atual = body.get("senha_atual") or ""
    nova_senha = body.get("nova_senha") or ""
    if not nova_senha or len(nova_senha) < 8:
        return _erro("SENHA_CURTA", "nova senha deve ter no minimo 8 caracteres", 400)
    ok = _obter_svc().alterar_senha(user.id, senha_atual, nova_senha)
    if not ok:
        security_logger.info(
            "evento=auth_cliente_alterar_senha_negado user_id=%s ip=%s", user.id, _ip_cliente(),
        )
        return _erro("SENHA_INVALIDA", "senha atual incorreta", 403)
    security_logger.info(
        "evento=auth_cliente_senha_alterada user_id=%s ip=%s", user.id, _ip_cliente(),
    )
    return jsonify({"status": "success", "ok": True})


@cliente_auth_bp.route("/email", methods=["PATCH"])
def alterar_email():
    """Troca email do user logado. Body: {senha_atual, novo_email}.
    Codigos: SENHA_INVALIDA (403), EMAIL_INVALIDO (400), EMAIL_JA_CADASTRADO (409).
    """
    cookie = request.cookies.get(COOKIE_NAME, "")
    user = _obter_svc().validar_cookie(cookie)
    if user is None:
        return _erro("NAO_AUTENTICADO", "sessao ausente ou invalida", 401)
    body = request.get_json(silent=True) or {}
    senha_atual = body.get("senha_atual") or ""
    novo_email = body.get("novo_email") or ""
    codigo = _obter_svc().alterar_email(user.id, senha_atual, novo_email)
    if codigo is None:
        security_logger.info(
            "evento=auth_cliente_email_alterado user_id=%s ip=%s", user.id, _ip_cliente(),
        )
        return jsonify({"status": "success", "ok": True})
    status = {"SENHA_INVALIDA": 403, "EMAIL_INVALIDO": 400, "EMAIL_JA_CADASTRADO": 409}[codigo]
    security_logger.info(
        "evento=auth_cliente_alterar_email_negado user_id=%s code=%s ip=%s",
        user.id, codigo, _ip_cliente(),
    )
    return _erro(codigo, codigo.lower().replace("_", " "), status)


@cliente_auth_bp.route("/configuracoes", methods=["GET"])
def configuracoes():
    """Settings do cliente: user + site + publishable_keys ativas + quota + consumo.

    Tudo escopado pelo `site_id` do cookie — anti-IDOR. Cliente A nao consegue
    ver dados do cliente B nem passando ?site_id no query (ignorado).
    """
    cookie = request.cookies.get(COOKIE_NAME, "")
    user = _obter_svc().validar_cookie(cookie)
    if user is None:
        return _erro("NAO_AUTENTICADO", "sessao ausente ou invalida", 401)

    if _tenants_repo is None:
        return _erro("BACKEND_INCOMPLETO", "tenants_repo nao configurado", 500)

    site = _tenants_repo.obter_site(user.site_id)
    if site is None:
        # cookie valido mas site sumiu (rare race condition: admin deletou)
        return _erro("SITE_NAO_ENCONTRADO", "site associado nao existe", 404)

    keys_ativas = [
        {
            "key_id": k.key_id,
            "valor": k.valor,
            "nome": k.nome,
            "ambiente": _ambiente_de_pk(k.valor),
        }
        for k in _tenants_repo.listar_publishable_keys(user.site_id)
        if not k.revogada
    ]

    quota = _tenants_repo.obter_quota(user.site_id)
    if quota is not None:
        quota_dict = {
            "eventos_por_minuto": quota.eventos_por_minuto,
            "eventos_por_dia": quota.eventos_por_dia,
            "emissoes_jwt_por_minuto": quota.emissoes_jwt_por_minuto,
            "retencao_dias": quota.retencao_dias,
        }
    else:
        # Defaults se quota nao foi inserida (deveria sempre existir via trigger
        # ON sites INSERT, mas defensive).
        quota_dict = {
            "eventos_por_minuto": 600,
            "eventos_por_dia": 100_000,
            "emissoes_jwt_por_minuto": 5,
            "retencao_dias": 30,
        }

    consumo_hoje = _tenants_repo.consumo_hoje(user.site_id)

    # Cardinalidade: tracker em memoria (in-process). Limite vem do plano
    # via LIMITE_POR_PLANO. Best-effort: se import falhar (test env minimo),
    # responde 0/0 em vez de quebrar o endpoint.
    try:
        from ingestao.cardinalidade import limite_para_plano, obter_tracker
        tracker = obter_tracker()
        cardinalidade_atual = tracker.total_para_site(user.site_id)
        cardinalidade_limite = limite_para_plano(site.plano)
    except Exception:
        cardinalidade_atual, cardinalidade_limite = 0, 0

    return jsonify({
        "user": {
            "id": user.id,
            "email": user.email,
            "papel": user.papel,
        },
        "site": {
            "id": site.id,
            "slug": site.slug,
            "nome": site.nome,
            "ambiente": site.ambiente,
            "plano": site.plano,
            "bucket_name": site.bucket_name,
        },
        "publishable_keys": keys_ativas,
        "quota": quota_dict,
        "consumo": {
            "eventos_hoje": consumo_hoje,
        },
        "cardinalidade": {
            "atual": cardinalidade_atual,
            "limite": cardinalidade_limite,
        },
    })


@cliente_auth_bp.route("/gate", methods=["GET"])
def gate():
    """Endpoint do nginx `auth_request`. Nao retorna body util — so codigo + headers.

    Sucesso: 200 + header `X-WEBAUTH-USER: <site_id>` que o nginx propaga
    pro Grafana (auth.proxy confia nele e cria/mapeia o user).
    Falha:   401. Nginx aborta a requisicao.

    Sprint 2 — sincroniza membership na org `cliente_<slug>` em best-effort
    (cache TTL 1h). Falha de sync NAO derruba o /gate; cookie ainda eh valido.
    """
    cookie = request.cookies.get(COOKIE_NAME, "")
    user = _obter_svc().validar_cookie(cookie)
    if user is None:
        security_logger.info("evento=auth_cliente_gate_negado ip=%s", _ip_cliente())
        return ("", 401)
    security_logger.info(
        "evento=auth_cliente_gate_ok site_id=%s user_id=%s", user.site_id, user.id,
    )
    _sincronizar_grafana_org(user.site_id)
    resp = make_response("", 200)
    resp.headers["X-WEBAUTH-USER"] = user.site_id
    resp.headers["X-WEBAUTH-PAPEL"] = user.papel
    return resp


def _sincronizar_grafana_org(site_id: str) -> None:
    """Best-effort: garante user na org cliente_<slug>. No-op se nao configurado."""
    if _grafana_sync is None or _tenants_repo is None:
        return
    try:
        site = _tenants_repo.obter_site(site_id)
    except Exception as erro:
        logger.warning("evento=grafana_sync_lookup_falhou site_id=%s motivo=%s", site_id, erro)
        return
    if site is None or not site.slug:
        return
    org_name = f"cliente_{site.slug}"
    _grafana_sync.garantir_membership(login=site_id, org_name=org_name)


@cliente_auth_bp.route("/magic-link/solicitar", methods=["POST"])
def solicitar_magic_link():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    if not email:
        # mesmo para email vazio retornamos 200 pra nao dar pista de validacao
        return jsonify({"status": "success", "ok": True})

    ip = _ip_cliente()
    svc = _obter_svc()
    try:
        criado = svc.solicitar_magic_link(email, ip=ip)
    except RateLimitExcedido as e:
        # Nao conta como 200 porque isto e abuso observavel (nao vaza quem usa).
        security_logger.info("evento=auth_cliente_magic_rate_limit ip=%s motivo=%s", ip, e)
        return _erro("RATE_LIMIT_EXCEDIDO", "muitas solicitacoes — tente novamente em 15min", 429)

    if criado is None:
        # email nao existe — resposta 200 identica (anti-enumeracao)
        security_logger.info("evento=auth_cliente_magic_solicitado_fantasma ip=%s", ip)
        return jsonify({"status": "success", "ok": True})

    link = _construir_link_verificar(criado.token_plaintext)
    _obter_email_sender().enviar(
        destinatario=email,
        assunto="Seu link de acesso ao dashboard",
        corpo_texto=(
            "Clique no link abaixo para acessar seu dashboard de metricas. "
            "Ele expira em 15 minutos e so pode ser usado uma vez.\n\n"
            f"{link}\n\n"
            "Se voce nao solicitou este e-mail, ignore-o."
        ),
    )
    security_logger.info(
        "evento=auth_cliente_magic_solicitado user_id=%s ip=%s",
        criado.magic_link.user_id, ip,
    )
    return jsonify({"status": "success", "ok": True})


@cliente_auth_bp.route("/magic-link/verificar", methods=["GET"])
def verificar_magic_link():
    token = request.args.get("t", "")
    if not token:
        return _erro("TOKEN_AUSENTE", "parametro t obrigatorio", 400)

    svc = _obter_svc()
    ip = _ip_cliente()
    ua = request.headers.get("User-Agent")
    sessao = svc.consumir_magic_link(token, ip=ip, user_agent=ua)
    if sessao is None:
        security_logger.info("evento=auth_cliente_magic_invalido ip=%s", ip)
        return _erro("TOKEN_INVALIDO", "link expirado ou ja utilizado", 400)

    destino = os.environ.get("DASHBOARD_REDIRECT", "/cliente/metricas")
    resp = make_response(redirect(destino, code=302))
    _set_cookie(resp, sessao.cookie_plaintext, max_age=svc._sessao_ttl)  # noqa: SLF001
    security_logger.info(
        "evento=auth_cliente_magic_consumido user_id=%s ip=%s",
        sessao.sessao.user_id, ip,
    )
    return resp


def _api_base() -> str:
    """URL raiz do proprio backend — usada em links de email (magic-link, reset).
    Fallback em DASHBOARD_BASE_URL para retrocompat enquanto Ansible nao rotacionar."""
    return os.environ.get(
        "API_BASE_URL",
        os.environ.get("DASHBOARD_BASE_URL", "https://api.dsplayground.com.br"),
    ).rstrip("/")


def _landing_base() -> str:
    """URL raiz da landing (CF Pages) — usada em redirects para paginas estaticas."""
    return os.environ.get("LANDING_BASE_URL", "https://dsplayground.com.br").rstrip("/")


def _construir_link_verificar(token: str) -> str:
    return f"{_api_base()}/cliente/auth/magic-link/verificar?{urlencode({'t': token})}"


def _construir_link_recuperar(token: str) -> str:
    return f"{_api_base()}/cliente/auth/recuperar-senha/verificar?{urlencode({'t': token})}"


# ============================================================================
# RECUPERACAO DE SENHA — fluxo separado de magic-link de login
# ============================================================================
# Magic-link de login (acima) entra direto no dashboard. Esses 3 endpoints
# fazem o fluxo de "esqueci minha senha" proper:
#   1. solicitar  → gera magic-link tipo='reset', envia email
#   2. verificar  → valida sem consumir; redireciona pra form na landing
#                   /cliente/redefinir-senha?t=<token>
#   3. confirmar  → POST com {token, nova_senha} — consome token, troca
#                   senha (sem exigir senha atual), cria sessao
#
# Por que separado: token de 'reset' nao deve criar sessao por si so. Se
# email do user vazar, atacante NAO entra direto — precisa SETAR uma nova
# senha (que invalida a antiga em qualquer outra sessao). Endereca achado
# SEC-CRIT da auditoria 2026-05-02.

@cliente_auth_bp.route("/recuperar-senha/solicitar", methods=["POST"])
def solicitar_recuperar_senha():
    """Body: {email}. Sempre retorna 200 (anti-enumeracao). Envia email com
    link pra `/cliente/auth/recuperar-senha/verificar?t=<token>`."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    if not email:
        return jsonify({"status": "success", "ok": True})

    ip = _ip_cliente()
    svc = _obter_svc()
    try:
        criado = svc.solicitar_magic_link(email, ip=ip, tipo="reset")
    except RateLimitExcedido as e:
        security_logger.info(
            "evento=auth_cliente_reset_rate_limit ip=%s motivo=%s", ip, e,
        )
        return _erro(
            "RATE_LIMIT_EXCEDIDO",
            "muitas solicitacoes — tente novamente em 15min",
            429,
        )

    if criado is None:
        security_logger.info("evento=auth_cliente_reset_solicitado_fantasma ip=%s", ip)
        return jsonify({"status": "success", "ok": True})

    link = _construir_link_recuperar(criado.token_plaintext)
    _obter_email_sender().enviar(
        destinatario=email,
        assunto="Redefinir sua senha",
        corpo_texto=(
            "Voce solicitou redefinir sua senha. Clique no link abaixo nos "
            "proximos 15 minutos pra escolher uma senha nova.\n\n"
            f"{link}\n\n"
            "Se voce NAO solicitou, ignore este email — sua senha atual "
            "continua valida e nada muda."
        ),
    )
    security_logger.info(
        "evento=auth_cliente_reset_solicitado user_id=%s ip=%s",
        criado.magic_link.user_id, ip,
    )
    return jsonify({"status": "success", "ok": True})


@cliente_auth_bp.route("/recuperar-senha/verificar", methods=["GET"])
def verificar_recuperar_senha():
    """GET com `?t=<token>`. NAO consome o token — so valida + redireciona
    pra pagina estatica de form de nova senha (na landing CF Pages).
    Form vai chamar POST /confirmar com o mesmo token + nova senha."""
    token = request.args.get("t", "")
    if not token:
        return _erro("TOKEN_AUSENTE", "parametro t obrigatorio", 400)

    svc = _obter_svc()
    magic = svc.validar_magic_link_reset(token)
    ip = _ip_cliente()
    if magic is None:
        security_logger.info(
            "evento=auth_cliente_reset_token_invalido ip=%s", ip,
        )
        return redirect(f"{_landing_base()}/cliente/redefinir-senha?erro=token_invalido", code=302)

    # Token valido. Redireciona pra form passando o token (vai virar
    # POST /confirmar quando user submeter).
    destino = f"{_landing_base()}/cliente/redefinir-senha?{urlencode({'t': token})}"
    security_logger.info(
        "evento=auth_cliente_reset_form_aberto user_id=%s ip=%s",
        magic.user_id, ip,
    )
    return redirect(destino, code=302)


@cliente_auth_bp.route("/recuperar-senha/confirmar", methods=["POST"])
def confirmar_recuperar_senha():
    """Body: {token, nova_senha}. Consome token, troca senha, cria sessao."""
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    nova_senha = body.get("nova_senha") or ""

    if not token:
        return _erro("TOKEN_AUSENTE", "campo `token` obrigatorio", 400)
    if not nova_senha or len(nova_senha) < _SENHA_MIN:
        return _erro(
            "SENHA_CURTA",
            f"nova_senha precisa ter pelo menos {_SENHA_MIN} caracteres",
            400,
        )

    svc = _obter_svc()
    ip = _ip_cliente()
    ua = request.headers.get("User-Agent")
    sessao = svc.consumir_magic_link_reset(token, nova_senha, ip=ip, user_agent=ua)
    if sessao is None:
        security_logger.info(
            "evento=auth_cliente_reset_confirm_invalido ip=%s", ip,
        )
        return _erro(
            "TOKEN_INVALIDO",
            "link expirado, ja utilizado ou senha muito curta",
            400,
        )

    # Sucesso — cria cookie de sessao + retorna 200 (frontend redireciona
    # via JS apos receber a resposta).
    user = _obter_svc()._repo.obter_user(sessao.sessao.user_id)  # noqa: SLF001
    resp = make_response(jsonify({
        "status": "success",
        "user": {
            "id": user.id, "site_id": user.site_id,
            "email": user.email, "papel": user.papel,
        } if user else None,
        "redirect": os.environ.get("DASHBOARD_REDIRECT", "/cliente/metricas"),
    }))
    _set_cookie(resp, sessao.cookie_plaintext, max_age=svc._sessao_ttl)  # noqa: SLF001
    security_logger.info(
        "evento=auth_cliente_reset_confirmado user_id=%s ip=%s",
        sessao.sessao.user_id, ip,
    )
    return resp


__all__ = ["cliente_auth_bp", "configurar", "COOKIE_NAME"]
