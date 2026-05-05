"""Blueprint de autenticacao do SDK.

Endpoint publico `POST /auth/sdk-token`:
  entrada: { "publishable_key": "pk_..." } + header Origin
  saida OK: { token, expires_in, server_time, last_received_id_registro, ... }
  saida erro: { status: "error", code, message }

Validacoes:
  1. publishable_key existe e nao esta revogada; site ativo.
  2. Origin normalizado esta na allowlist do site.
  3. Rate limit de emissao por publishable_key (quotas.emissoes_jwt_por_minuto).
  4. Quota diaria nao estourada.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, jsonify, request

from .jwt_service import obter_servico as obter_jwt_service
from .middleware import normalizar_origin
from .tenants_repo import obter_repo


logger = logging.getLogger("auth.routes")


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


SCHEMA_VERSION_SERVIDOR = "1.2"
SCHEMA_VERSION_MINIMO_CLIENTE = "1.0"  # Schema 1.1 (SDK 0.3.x) ainda aceito.


def _erro(code: str, message: str, status: int):
    return (
        jsonify({"status": "error", "code": code, "message": message}),
        status,
    )


def _ip_cliente() -> Optional[str]:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.environ.get("REMOTE_ADDR")


def _obter_ultimo_recebido(analytics_session_id: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """Consulta o registro do ultimo id_registro aceito para uma sessao logica.

    Retorna (last_received_id_registro, last_received_at_ms). Usado pelo SDK
    na reconexao para descartar itens da fila local que o backend ja processou.
    """
    if not analytics_session_id:
        return None, None
    from ingestao.idempotencia import obter_registro_ultimo
    return obter_registro_ultimo().obter(analytics_session_id)


@auth_bp.route("/sdk-token", methods=["POST"])
def emitir_sdk_token():
    body = request.get_json(silent=True) or {}
    publishable_valor = body.get("publishable_key")
    if not publishable_valor or not isinstance(publishable_valor, str):
        return _erro("PUBLISHABLE_MISSING", "publishable_key obrigatoria", 400)

    origin = normalizar_origin(request.headers.get("Origin"))
    if origin is None:
        return _erro("ORIGIN_MISSING", "Origin invalido ou ausente", 400)

    # Negociacao de schema (Onda 3 — mas ja e aplicada aqui porque a resposta
    # deste endpoint ja carrega os campos de schema).
    schema_cliente = request.headers.get("X-SDK-Schema-Version", SCHEMA_VERSION_MINIMO_CLIENTE)
    if _versao_menor_que(schema_cliente, SCHEMA_VERSION_MINIMO_CLIENTE):
        return _erro(
            "UNSUPPORTED_SCHEMA",
            f"Schema {schema_cliente} inferior ao minimo {SCHEMA_VERSION_MINIMO_CLIENTE}",
            426,
        )

    repo = obter_repo()

    publishable = repo.obter_publishable_por_valor(publishable_valor)
    if publishable is None or publishable.revogada:
        logger.info("auth=falha code=PUBLISHABLE_INVALID origin=%s", origin)
        return _erro("PUBLISHABLE_INVALID", "publishable_key invalida ou revogada", 401)

    site = repo.obter_site(publishable.site_id)
    if site is None or site.status != "ativo":
        logger.info("auth=falha code=SITE_INACTIVE site=%s", publishable.site_id)
        return _erro("SITE_INACTIVE", "Site inativo ou suspenso", 403)

    if not repo.origin_permitido(site.id, origin):
        logger.info(
            "auth=falha code=ORIGIN_NOT_ALLOWED site=%s origin=%s", site.id, origin
        )
        return _erro("ORIGIN_NOT_ALLOWED", "Origin nao autorizado para este site", 403)

    quota = repo.obter_quota(site.id)
    if quota is None:
        # defensivo; criacao de site ja insere quota default
        return _erro("QUOTA_MISSING", "Quota nao configurada", 500)

    emissoes_recentes = repo.contar_emissoes_recentes(publishable.key_id, janela_segundos=60)
    if emissoes_recentes >= quota.emissoes_jwt_por_minuto:
        logger.info(
            "auth=falha code=RATE_LIMIT_EMISSION site=%s recent=%d",
            site.id,
            emissoes_recentes,
        )
        return _erro(
            "RATE_LIMIT_EMISSION",
            f"Limite de {quota.emissoes_jwt_por_minuto} emissoes/min atingido",
            429,
        )

    consumo_hoje = repo.consumo_hoje(site.id)
    if consumo_hoje >= quota.eventos_por_dia:
        logger.info(
            "auth=falha code=QUOTA_EXCEEDED site=%s hoje=%d limite=%d",
            site.id,
            consumo_hoje,
            quota.eventos_por_dia,
        )
        return _erro("QUOTA_EXCEEDED", "Cota diaria de eventos excedida", 429)

    # Tudo ok — emite.
    from flask import current_app
    ttl = int(current_app.config.get("SDK_TOKEN_TTL_SECONDS", 300))
    jwt_service = obter_jwt_service()

    token, claims = jwt_service.emitir_sdk_jwt(
        site_id=site.id,
        app_id=site.slug,
        ambiente=site.ambiente,
        ttl_seconds=ttl,
        scope="ingest",
    )
    repo.registrar_emissao(
        site_id=site.id,
        publishable_id=publishable.key_id,
        jti=claims.jti,
        origin=origin,
        ip=_ip_cliente(),
    )

    analytics_session_id = body.get("analytics_session_id")
    last_id, last_at = _obter_ultimo_recebido(analytics_session_id)

    resposta = {
        "status": "success",
        "token": token,
        "expires_in": ttl,
        "server_time": int(datetime.now(timezone.utc).timestamp() * 1000),
        "server_schema_version": SCHEMA_VERSION_SERVIDOR,
        "min_client_schema": SCHEMA_VERSION_MINIMO_CLIENTE,
        "last_received_id_registro": last_id,
        "last_received_at": last_at,
    }
    return jsonify(resposta), 200


def _versao_menor_que(a: str, b: str) -> bool:
    """Compara versoes semver simples "X.Y" — retorna True se a < b."""

    def parse(v: str) -> tuple[int, int]:
        try:
            partes = v.split(".")
            return (int(partes[0]), int(partes[1]) if len(partes) > 1 else 0)
        except (ValueError, IndexError):
            return (0, 0)

    return parse(a) < parse(b)
