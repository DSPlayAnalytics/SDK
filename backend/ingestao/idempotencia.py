"""Garantias da Onda 1: idempotencia, rastreio do ultimo recebido e sequenciador.

Mantido propositalmente em memoria simples — LRU + TTL com lock. Substituir por
Redis quando a arquitetura comercial subir, mantendo a mesma interface publica.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class EntradaIdempotencia:
    resumo_dict: dict           # ack serializado (retornado em caso de hit)
    server_seq: int             # seq monotonico emitido na primeira aceitacao
    server_time_ms: int         # instante da primeira aceitacao


class CacheIdempotencia:
    """LRU + TTL para deduplicar `(site_id, id_registro)`.

    - TTL default 10 min (padrao comum; o payload ja esta no InfluxDB ao chegar aqui).
    - Capacidade default 50k entradas; suficiente para ~83 eventos/s de pico por 10 min.
    - Thread-safe.
    """

    def __init__(self, ttl_segundos: int = 600, capacidade: int = 50_000):
        self._ttl = ttl_segundos
        self._cap = capacidade
        self._lock = threading.RLock()
        self._entries: OrderedDict[tuple[str, str], tuple[EntradaIdempotencia, float]] = OrderedDict()

    def _chave(self, site_id: Optional[str], id_registro: str) -> tuple[str, str]:
        return (site_id or "_semsite_", id_registro)

    def ver(self, site_id: Optional[str], id_registro: str) -> Optional[EntradaIdempotencia]:
        if not id_registro:
            return None
        chave = self._chave(site_id, id_registro)
        agora = time.time()
        with self._lock:
            item = self._entries.get(chave)
            if item is None:
                return None
            entrada, registrada_em = item
            if agora - registrada_em > self._ttl:
                self._entries.pop(chave, None)
                return None
            # LRU: renova posicao
            self._entries.move_to_end(chave)
            return entrada

    def gravar(self, site_id: Optional[str], id_registro: str, entrada: EntradaIdempotencia) -> None:
        if not id_registro:
            return
        chave = self._chave(site_id, id_registro)
        with self._lock:
            self._entries[chave] = (entrada, time.time())
            self._entries.move_to_end(chave)
            while len(self._entries) > self._cap:
                self._entries.popitem(last=False)

    def limpar_expirados(self) -> int:
        agora = time.time()
        removidos = 0
        with self._lock:
            chaves = list(self._entries.keys())
            for chave in chaves:
                _, registrada_em = self._entries[chave]
                if agora - registrada_em > self._ttl:
                    self._entries.pop(chave, None)
                    removidos += 1
        return removidos

    def tamanho(self) -> int:
        with self._lock:
            return len(self._entries)


@dataclass
class _UltimaMarcacao:
    id_registro: str
    ts_ms: int


class RegistroUltimoRecebido:
    """Mantem o ultimo `id_registro` aceito por sessao logica de analytics.

    Usado no ack de connect e no retorno de `/auth/sdk-token` para permitir
    ao SDK descartar itens de fila que o backend ja processou antes da reconexao.

    Chaveado por `session_id` logico do analytics (NAO o `sid` do Socket.IO).
    """

    def __init__(self, ttl_segundos: int = 3600, capacidade: int = 50_000):
        self._ttl = ttl_segundos
        self._cap = capacidade
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, tuple[_UltimaMarcacao, float]] = OrderedDict()

    def registrar(self, session_id: str, id_registro: str, ts_ms: Optional[int] = None) -> None:
        if not session_id or not id_registro:
            return
        ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
        with self._lock:
            self._entries[session_id] = (_UltimaMarcacao(id_registro=id_registro, ts_ms=ts), time.time())
            self._entries.move_to_end(session_id)
            while len(self._entries) > self._cap:
                self._entries.popitem(last=False)

    def obter(self, session_id: str) -> tuple[Optional[str], Optional[int]]:
        if not session_id:
            return None, None
        agora = time.time()
        with self._lock:
            item = self._entries.get(session_id)
            if item is None:
                return None, None
            marca, registrada_em = item
            if agora - registrada_em > self._ttl:
                self._entries.pop(session_id, None)
                return None, None
            self._entries.move_to_end(session_id)
            return marca.id_registro, marca.ts_ms


class SequenciadorServidor:
    """Emissor de numeros monotonicos por `site_id`."""

    def __init__(self):
        self._lock = threading.Lock()
        self._contadores: dict[str, int] = {}

    def proximo(self, site_id: Optional[str]) -> int:
        chave = site_id or "_semsite_"
        with self._lock:
            prox = self._contadores.get(chave, 0) + 1
            self._contadores[chave] = prox
            return prox


# ---------- singletons ----------

_cache: Optional[CacheIdempotencia] = None
_ultimos: Optional[RegistroUltimoRecebido] = None
_sequencia: Optional[SequenciadorServidor] = None
_lock_mod = threading.Lock()


def obter_cache_idempotencia() -> CacheIdempotencia:
    global _cache
    with _lock_mod:
        if _cache is None:
            _cache = CacheIdempotencia()
        return _cache


def obter_registro_ultimo() -> RegistroUltimoRecebido:
    global _ultimos
    with _lock_mod:
        if _ultimos is None:
            _ultimos = RegistroUltimoRecebido()
        return _ultimos


def obter_sequenciador() -> SequenciadorServidor:
    global _sequencia
    with _lock_mod:
        if _sequencia is None:
            _sequencia = SequenciadorServidor()
        return _sequencia


def resetar_tudo() -> None:
    """Apenas para testes."""
    global _cache, _ultimos, _sequencia
    with _lock_mod:
        _cache = None
        _ultimos = None
        _sequencia = None
