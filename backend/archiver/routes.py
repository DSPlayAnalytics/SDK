"""Blueprint /cliente/exportar — download de arquivos arquivados pelo cliente.

Auth: cookie cliente_session validado pelo mesmo SessaoService usado em
/cliente/auth/me. Anti-IDOR: key R2 sempre montada do `slug` do user atual,
nunca do path/query.

Endpoints:
  GET /cliente/exportar           — JSON com lista de dias arquivados
  GET /cliente/exportar/<YYYY-MM-DD> — 302 redirect pra signed URL R2 (TTL 5min)
"""
import logging
import re
from typing import Optional

from flask import Blueprint, jsonify, redirect, request

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

COOKIE_NAME = 'cliente_session'
_RE_DIA = re.compile(r'^\d{4}-\d{2}-\d{2}$')

cliente_export_bp = Blueprint('cliente_export', __name__, url_prefix='/cliente')


# ---- DI singletons (mesmo padrao do cliente_routes.py) ----
_svc = None
_tenants_repo = None
_r2_client = None
_ttl_signed_url = 300


def configurar(svc, tenants_repo, r2_client, ttl_signed_url: int = 300):
    global _svc, _tenants_repo, _r2_client, _ttl_signed_url
    _svc = svc
    _tenants_repo = tenants_repo
    _r2_client = r2_client
    _ttl_signed_url = ttl_signed_url


def _user_atual():
    cookie = request.cookies.get(COOKIE_NAME, '')
    if _svc is None:
        return None
    return _svc.validar_cookie(cookie)


def _slug_do_user(user) -> Optional[str]:
    if _tenants_repo is None:
        return None
    site = _tenants_repo.obter_site(user.site_id)
    if site is None:
        return None
    return getattr(site, 'slug', None)


def _key_do_dia(slug: str, dia: str) -> str:
    """slug='acme', dia='2026-04-30' -> 'acme/2026/04/30.lp.gz'."""
    yyyy, mm, dd = dia.split('-')
    return f'{slug}/{yyyy}/{mm}/{dd}.lp.gz'


@cliente_export_bp.route('/exportar', methods=['GET'])
def listar_arquivos():
    user = _user_atual()
    if user is None:
        return ('', 401)

    slug = _slug_do_user(user)
    if slug is None:
        return jsonify({'arquivos': []})

    keys = _r2_client.listar_arquivos_do_slug(slug)

    arquivos = []
    for key in keys:
        # key = '<slug>/YYYY/MM/DD.lp.gz' — extrai dia
        sem_prefix = key[len(slug) + 1:]  # remove "<slug>/"
        partes = sem_prefix.replace('.lp.gz', '').split('/')
        if len(partes) == 3:
            dia = f'{partes[0]}-{partes[1]}-{partes[2]}'
            arquivos.append({'dia': dia, 'key': key})

    security_logger.info(
        f'evento=exportar_listagem site_id={user.site_id} slug={slug} qtd={len(arquivos)}'
    )
    return jsonify({'arquivos': arquivos})


@cliente_export_bp.route('/exportar/<dia>', methods=['GET'])
def baixar_arquivo(dia: str):
    if not _RE_DIA.match(dia or ''):
        return jsonify({'error': 'dia invalido — use YYYY-MM-DD'}), 400

    user = _user_atual()
    if user is None:
        return ('', 401)

    slug = _slug_do_user(user)
    if slug is None:
        return ('', 404)

    key = _key_do_dia(slug, dia)

    # Confirma que o arquivo existe antes de presignar — alternativa eh deixar
    # o R2 retornar 404 no GET, mas signed URL aponta sempre pra mesma path
    # mesmo sem objeto, ai cliente toma 404 esquisito.
    keys_existentes = _r2_client.listar_arquivos_do_slug(slug)
    if key not in keys_existentes:
        return ('', 404)

    url = _r2_client.signed_url_para_download(key=key, ttl_segundos=_ttl_signed_url)
    security_logger.info(
        f'evento=exportar_download site_id={user.site_id} slug={slug} dia={dia} ttl={_ttl_signed_url}'
    )
    return redirect(url, code=302)
