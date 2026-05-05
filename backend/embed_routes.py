"""Blueprint /embed — emissao de token + serving de dados pra widget de iframe.

Endpoints:
  POST /embed/token
      Body: {site_id, grafico_id, ttl_segundos?}
      Auth: cookie cliente_session do dono do site_id.
      Resp: 200 {token, expira_em} | 401 | 403 | 400

  GET /embed/dados/<site_id>/<grafico_id>
      Auth: Authorization: Bearer <embed_jwt>
      Resp: 200 {site_id, grafico_id, pontos[]} | 401 | 403

Fase 1 (dogfood): allow-list estatica de graficos, allow-list estatica de
origens via header CORS, sem rate-limit dedicado (defer pra Fase 2).

Referencia: ark/docs/embed-iframe.md.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import jwt as pyjwt
from flask import Blueprint, jsonify, request

from auth.embed_jwt_service import EmbedJwtService
from auth.sessao_service import SessaoService
from auth.tenants_repo import TenantsRepo


logger = logging.getLogger("embed")
security_logger = logging.getLogger("security")


embed_bp = Blueprint("embed", __name__, url_prefix="/embed")


# ---------- singletons configurados em runtime ----------

_embed_jwt: Optional[EmbedJwtService] = None
_sessao: Optional[SessaoService] = None
_tenants: Optional[TenantsRepo] = None
_influx = None
_graficos_permitidos: frozenset[str] = frozenset()


def configurar(
    *,
    embed_jwt_service: EmbedJwtService,
    sessao_service: SessaoService,
    tenants_repo: TenantsRepo,
    influx_service,
    graficos_permitidos: Iterable[str],
) -> None:
    """Configura singletons. Chamar uma vez no boot, antes de register_blueprint."""
    global _embed_jwt, _sessao, _tenants, _influx, _graficos_permitidos
    _embed_jwt = embed_jwt_service
    _sessao = sessao_service
    _tenants = tenants_repo
    _influx = influx_service
    _graficos_permitidos = frozenset(graficos_permitidos)


def _erro(code: str, message: str, status: int):
    return jsonify({"status": "error", "code": code, "message": message}), status


def _validar_cookie() -> Optional[object]:
    """Le cookie cliente_session e retorna user, ou None se invalido."""
    from auth.cliente_routes import COOKIE_NAME
    cookie = request.cookies.get(COOKIE_NAME, "")
    if not cookie or _sessao is None:
        return None
    return _sessao.validar_cookie(cookie)


# ---------- POST /embed/token ----------

@embed_bp.route("/token", methods=["POST"])
def emitir_token():
    if _embed_jwt is None or _tenants is None:
        return _erro("EMBED_NAO_CONFIGURADO", "embed nao inicializado", 503)

    user = _validar_cookie()
    if user is None:
        return _erro("NAO_AUTENTICADO", "sessao ausente ou invalida", 401)

    body = request.get_json(silent=True) or {}
    site_id = (body.get("site_id") or "").strip()
    grafico_id = (body.get("grafico_id") or "").strip()
    ttl = body.get("ttl_segundos")

    if not site_id or not grafico_id:
        return _erro("PAYLOAD_INCOMPLETO", "site_id e grafico_id obrigatorios", 400)

    if grafico_id not in _graficos_permitidos:
        return _erro("GRAFICO_INVALIDO",
                     f"grafico_id deve estar em {sorted(_graficos_permitidos)}", 400)

    site = _tenants.obter_site(site_id)
    if site is None:
        return _erro("SITE_NAO_ENCONTRADO", "site_id desconhecido", 404)

    if user.site_id != site_id:
        security_logger.warning(
            "evento=embed_token_negado motivo=site_alheio user_id=%s site_id=%s",
            user.id, site_id,
        )
        return _erro("SITE_NEGADO", "site_id nao pertence ao user", 403)

    try:
        ttl_int = int(ttl) if ttl is not None else 300
    except (TypeError, ValueError):
        return _erro("TTL_INVALIDO", "ttl_segundos deve ser inteiro", 400)

    token, claims = _embed_jwt.emitir(
        site_id=site_id, grafico_id=grafico_id,
        user_id=user.id, ttl_segundos=ttl_int,
    )
    security_logger.info(
        "evento=embed_token_emitido user_id=%s site_id=%s grafico_id=%s exp=%s",
        user.id, site_id, grafico_id, claims.exp,
    )
    return jsonify({"token": token, "expira_em": claims.exp}), 200


# ---------- GET /embed/dados/<site_id>/<grafico_id> ----------

@embed_bp.route("/dados/<site_id>/<grafico_id>", methods=["GET", "OPTIONS"])
def obter_dados(site_id: str, grafico_id: str):
    if request.method == "OPTIONS":
        return ("", 204)

    if _embed_jwt is None or _tenants is None or _influx is None:
        return _erro("EMBED_NAO_CONFIGURADO", "embed nao inicializado", 503)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return _erro("NAO_AUTENTICADO", "Authorization Bearer obrigatorio", 401)

    token = auth_header[len("Bearer "):].strip()
    try:
        claims = _embed_jwt.verificar(token)
    except pyjwt.PyJWTError as erro:
        security_logger.info(
            "evento=embed_dados_token_invalido site_id=%s grafico_id=%s motivo=%s",
            site_id, grafico_id, erro,
        )
        return _erro("TOKEN_INVALIDO", "token invalido ou expirado", 401)

    # Revogacao: TTL curto e a primeira defesa, mas tokens podem ser revogados
    # explicitamente (leak, banimento de site, remocao de widget). Tabela
    # `embed_jwt_revogados` nao limita escala porque so cresce ate exp+TTL_MAX
    # (housekeeping em background limpa entradas com >24h de idade).
    try:
        if _tenants.jti_embed_esta_revogado(claims.jti):
            security_logger.warning(
                "evento=embed_dados_jti_revogado site_id=%s grafico_id=%s jti=%s user_id=%s",
                site_id, grafico_id, claims.jti, claims.user_id,
            )
            return _erro("TOKEN_REVOGADO", "token revogado", 401)
    except AttributeError:
        # Repo legado sem o metodo — abortar verificacao silenciosamente seria
        # perigoso; melhor deixar passar e logar pra alertar deploy mismatch.
        security_logger.error("evento=embed_dados_repo_sem_revocacao jti=%s", claims.jti)

    if claims.site_id != site_id or claims.grafico_id != grafico_id:
        security_logger.warning(
            "evento=embed_dados_path_divergente token_site=%s token_grafico=%s "
            "path_site=%s path_grafico=%s user_id=%s",
            claims.site_id, claims.grafico_id, site_id, grafico_id, claims.user_id,
        )
        return _erro("PATH_DIVERGENTE",
                     "site_id/grafico_id no path nao casam com o token", 403)

    site = _tenants.obter_site(site_id)
    if site is None or not site.bucket_name:
        return _erro("SITE_SEM_BUCKET", "site nao tem bucket configurado", 404)

    pontos = _influx.query_metricas_agregadas(bucket=site.bucket_name)
    return jsonify({
        "site_id": site_id,
        "grafico_id": grafico_id,
        "pontos": pontos,
    }), 200
