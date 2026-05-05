"""CORS dinamico: combina lista estatica (vault) + lookup em site_dominios.

Usado pelo backend pra autorizar Origins de SDKs em sites de clientes registrados
sem precisar editar `cors_origins` no vault + ansible-apply a cada novo cliente.

Cache TTL evita hit no Postgres por requisicao. TTL default 60s — ajusta o
trade-off entre frescor (cliente recem-cadastrado vira CORS-OK em ate 60s) e
custo (DB hit a cada 60s por origin distinto).

Cache negativo: origens NAO registradas tambem cacheiam, pra evitar que um
ataque com Origin spoofado bata DB toda req.

Uso:
    svc = OriginsDinamicos(
        origins_estaticos=app.config["CORS_ORIGINS"],
        tenants_repo=tenants_repo_singleton,
        ttl_segundos=60,
    )
    if svc.permitido(request.headers.get("Origin")):
        ...
"""
from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)


class OriginsDinamicos:
    """Verifica se um Origin e permitido (estatico + dinamico via repo)."""

    def __init__(
        self,
        origins_estaticos: Iterable[str],
        tenants_repo,
        ttl_segundos: int = 60,
        agora: Optional[Callable[[], float]] = None,
    ):
        self._estaticos = frozenset(o.rstrip("/") for o in origins_estaticos if o)
        self._repo = tenants_repo
        self._ttl = ttl_segundos
        self._agora = agora or time.monotonic
        self._cache: dict[str, tuple[bool, float]] = {}
        self._lock = Lock()

    def permitido(self, origin: Optional[str]) -> bool:
        if not origin:
            return False

        normalizado = origin.rstrip("/")

        # Estatico — passa direto, nao cache pois e barato
        if normalizado in self._estaticos:
            return True

        # Dinamico — cache TTL
        agora = self._agora()
        with self._lock:
            cached = self._cache.get(normalizado)
            if cached is not None:
                resultado, expira_em = cached
                if expira_em > agora:
                    return resultado

        # Cache miss ou expirado — consulta repo
        try:
            registrado = bool(self._repo.dominio_existe(normalizado))
        except Exception as erro:
            # Falha de DB nao deve abrir CORS — log e nega
            logger.warning(
                f"evento=cors_dinamico_repo_falhou origin={origin!r} erro={erro!r}"
            )
            return False

        with self._lock:
            self._cache[normalizado] = (registrado, agora + self._ttl)

        return registrado

    def invalidar(self, origin: Optional[str] = None) -> None:
        """Limpa cache. None = limpa tudo; string = remove so esse origin.

        Util pra chamar apos `tenants_repo.adicionar_dominio` (cliente acabou
        de cadastrar) — o origin novo vira valido imediatamente, sem esperar
        TTL expirar.
        """
        with self._lock:
            if origin is None:
                self._cache.clear()
            else:
                self._cache.pop(origin.rstrip("/"), None)


__all__ = ["OriginsDinamicos"]
