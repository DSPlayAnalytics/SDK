"""Sync idempotente de membership Grafana — coloca user na org certa.

Problema: `auth.proxy` cria user automaticamente na "Main Org." (org id=1) com
role Viewer. Mas o datasource e a org do cliente sao `cliente_<slug>`. Sem
sincronizar membership, o user logado pelo cookie do dashboard NAO ve o
dataset do cliente — ve a Main Org vazia.

Solucao: apos cada `/gate` bem-sucedido (com cache TTL), garantir que:
  1. O user existe em Grafana (sera criado pelo proximo /api/* via auth.proxy
     se ainda nao existir; sync trata 404 graciosamente).
  2. O user e membro da org `cliente_<slug>` com role Viewer.
  3. A org `cliente_<slug>` e a "current org" do user (Grafana renderiza nela
     por default).

Cache: dict[(login, org_name) -> ts_unix], TTL default 1h. Em hot path de
nginx auth_request (cada request a /cliente/metricas/*) o lookup e O(1) e
nao bate na API Grafana se ja sincronizou.

Falhas (Grafana down, 500, timeouts) NAO derrubam o /gate. Logam warning e
seguem — o cookie ainda e valido, so a sincronizacao fica para a proxima.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from integrations.grafana_client import GrafanaClient


logger = logging.getLogger("auth.grafana_sync")


class GrafanaSyncService:
    """Encapsula a logica idempotente de membership + cache TTL."""

    def __init__(
        self,
        client: GrafanaClient,
        *,
        ttl_seconds: int = 3600,
        main_org_id: int = 1,
    ):
        self._client = client
        self._ttl = ttl_seconds
        self._main_org_id = main_org_id
        self._lock = threading.RLock()
        # cache de sync bem-sucedido: (login, org_name) -> monotonic_ts
        self._cache: dict[tuple[str, str], float] = {}

    def garantir_membership(self, login: str, org_name: str) -> bool:
        """Garante que `login` e membro+current da org `org_name` (idempotente).

        Retorna True quando ja sincronizado (cache hit) ou sincronizou agora.
        Retorna False se a sincronizacao falhou (loga warning).
        """
        if not login or not org_name:
            return False

        chave = (login, org_name)
        now = time.monotonic()

        with self._lock:
            ts = self._cache.get(chave)
            if ts is not None and (now - ts) < self._ttl:
                return True

        try:
            sucesso = self._sync(login, org_name)
        except Exception as erro:
            logger.warning(
                "evento=grafana_sync_falhou login=%s org=%s motivo=%s",
                login, org_name, erro,
            )
            return False

        if sucesso:
            with self._lock:
                self._cache[chave] = time.monotonic()
        return sucesso

    def _sync(self, login: str, org_name: str) -> bool:
        """Faz as chamadas de API. Pode lancar excecao — chamador captura."""
        # 1) Org alvo precisa existir. Em prod o `provisionar_cliente.py` ja criou.
        org = self._client.get_org_by_name(org_name)
        if not org:
            logger.warning(
                "evento=grafana_sync_org_inexistente login=%s org=%s "
                "(rode provisionar_cliente.py primeiro)",
                login, org_name,
            )
            return False
        target_org_id = org["id"]

        # 2) User ainda pode nao existir se for o primeiro request via auth.proxy.
        # Nesse caso retornamos False sem cachear — proximo /gate tenta de novo.
        user = self._client.get_user_by_login(login)
        if not user:
            logger.info(
                "evento=grafana_sync_user_pendente login=%s org=%s "
                "(auth.proxy criara no primeiro hit)",
                login, org_name,
            )
            return False
        user_id = user["id"]

        # 3) Adiciona ao org alvo. 409 = ja era membro (idempotente, OK).
        adicionado = self._client.add_org_user(target_org_id, login=login, role="Viewer")

        # 4) Define a org alvo como current — Grafana usa isso pra escolher
        # qual org renderizar quando o user abre o dashboard.
        self._client.set_user_current_org(user_id, target_org_id)

        logger.info(
            "evento=grafana_sync_ok login=%s org=%s user_id=%d adicionado=%s",
            login, org_name, user_id, adicionado,
        )
        return True

    def invalidar(self, login: str, org_name: str) -> None:
        with self._lock:
            self._cache.pop((login, org_name), None)

    def limpar(self) -> None:
        with self._lock:
            self._cache.clear()


def criar_servico_se_configurado() -> Optional[GrafanaSyncService]:
    """Instancia o servico se GRAFANA_URL + creds estao em env, senao None.

    Em dev local sem Grafana o servico nao roda — `/gate` continua funcionando
    sem sync (single-tenant na Main Org).
    """
    import os
    base_url = os.environ.get("GRAFANA_URL")
    user = os.environ.get("GRAFANA_ADMIN_USER")
    password = os.environ.get("GRAFANA_ADMIN_PASSWORD")
    if not (base_url and user and password):
        logger.info("evento=grafana_sync_desabilitado motivo=env_incompleto")
        return None
    client = GrafanaClient(base_url, user, password)
    ttl = int(os.environ.get("GRAFANA_SYNC_TTL_SECONDS", "3600"))
    return GrafanaSyncService(client, ttl_seconds=ttl)
