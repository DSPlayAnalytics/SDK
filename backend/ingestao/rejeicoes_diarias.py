"""Contador diário de eventos rejeitados por site (em memória).

Acumulado em processo — reseta na meia-noite UTC pelo emailer, ou no restart
(aceitável: perder um dia não é crítico para relatório). Thread-safe via Lock.

Uso:
    from ingestao.rejeicoes_diarias import obter_contador
    obter_contador().incrementar(site_id, "QUOTA_EXCEDIDA")
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict


class ContadorRejeicoesdiarias:
    """Acumula contagem de rejeições por (site_id, tipo) durante o dia."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {site_id: {tipo: count}}
        self._contadores: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def incrementar(self, site_id: str, tipo: str) -> None:
        if not site_id:
            return
        with self._lock:
            self._contadores[site_id][tipo] += 1

    def obter_e_resetar(self) -> Dict[str, Dict[str, int]]:
        """Retorna snapshot e limpa o estado. Chamado pelo emailer diário."""
        with self._lock:
            snapshot = {
                site_id: dict(tipos)
                for site_id, tipos in self._contadores.items()
                if any(v > 0 for v in tipos.values())
            }
            self._contadores.clear()
        return snapshot


_instancia: ContadorRejeicoesdiarias | None = None
_instancia_lock = threading.Lock()


def obter_contador() -> ContadorRejeicoesdiarias:
    global _instancia
    if _instancia is None:
        with _instancia_lock:
            if _instancia is None:
                _instancia = ContadorRejeicoesdiarias()
    return _instancia
