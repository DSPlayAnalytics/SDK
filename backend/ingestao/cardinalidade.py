"""Tracker em memoria de cardinalidade por site (sec 20 dashboard-cliente.md).

Cardinalidade alta em InfluxDB OSS = morte do bucket: cada combinacao unica
de tags vira uma serie. Cliente que mete `user_id` ou `request_id` como tag
explode em horas.

Estrategia sprint 2:
- Em memoria, rastreamos `site_id -> tag_name -> set(values)`.
- A cada ingest, simulamos a adicao das tags do payload e checamos contra
  o limite do plano. Se passar, rejeita o evento (sem mutar o store) e o
  ack carrega `code=CARDINALIDADE_EXCEDIDA`.
- Limites por plano (sec 18): free=1k, pequeno=5k, medio=50k, grande=500k.
- Reseta no restart do processo. Aceitavel — atacante teria que sustentar
  um bombardeio sem janela de cleanup; nesse cenario a quota diaria ja
  cortou bem antes.

Limitacoes (documentadas):
- Nao persistente entre restarts.
- Nao distribuido entre workers (em prod usamos 1 worker eventlet — alinha).
- Soma simples |set| por tag, nao o produto cartesiano (que e o killer real).
  Como proxy linear ao cartesiano, ainda detecta padroes maliciosos antes
  de derretir o Influx, com computacao trivial.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple


# Sec 18 do dashboard-cliente.md
LIMITE_POR_PLANO: Dict[str, int] = {
    "free":      1_000,
    "pequeno":   5_000,
    "medio":    50_000,
    "grande":  500_000,
}


def limite_para_plano(plano: Optional[str]) -> int:
    """Retorna o limite do plano. Plano desconhecido -> limite mais restritivo."""
    if not plano:
        return LIMITE_POR_PLANO["free"]
    return LIMITE_POR_PLANO.get(plano, LIMITE_POR_PLANO["free"])


class TrackerCardinalidade:
    """Mantem `site_id -> tag_name -> set(values)` thread-safe.

    Alerta progressivo: quando cardinalidade atinge 80% e 95% do limite,
    `alerta_pendente()` retorna o nivel uma unica vez. Permite log/email
    proativo antes do bloqueio em 100%.
    """

    # Niveis de alerta (porcentagens). Ordem importa: maiores primeiro pra
    # consumir antes em alerta_pendente.
    _NIVEIS_ALERTA = (95, 80)

    def __init__(self):
        self._lock = threading.RLock()
        self._stores: Dict[str, Dict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        # Para cada site, niveis ja emitidos (anti-spam — alerta de 80 emite
        # uma unica vez; reseta em invalidar_site).
        self._alertas_emitidos: Dict[str, Set[int]] = defaultdict(set)

    def verificar_e_registrar(
        self,
        site_id: Optional[str],
        pares: Iterable[Tuple[str, object]],
        limite: int,
    ) -> Tuple[bool, Optional[str], int]:
        """Simula adicao dos pares (tag, valor) e decide se aceita.

        Aceita pares com tags repetidas — um batch com 3 page_types vira
        3 entradas (page_type, "/"), (page_type, "/sobre"), (page_type, "/contato").

        Retorna (ok, tag_dominante, total_apos).

        - ok=True: aceitou; valores ja foram adicionados ao store.
        - ok=False: rejeitou; store NAO foi mutado (atacante nao consegue
          inflar cardinalidade so mandando lixo).
        - tag_dominante: tag com maior |set| no momento da rejeicao
          (alerta direcionado pra cliente).
        - total_apos: soma de |set| em todos os tags depois da operacao
          (se aceito) ou o que seria (se rejeitado).
        """
        if not site_id:
            return True, None, 0

        # Sanitiza e dedup local: pares com mesma chave+valor viram um.
        novos: List[Tuple[str, str]] = []
        seen: Set[Tuple[str, str]] = set()
        for tag, valor in pares:
            if valor is None or valor == "":
                continue
            par = (tag, str(valor))
            if par in seen:
                continue
            seen.add(par)
            novos.append(par)
        if not novos:
            return True, None, 0

        with self._lock:
            store = self._stores[site_id]
            total_atual = sum(len(s) for s in store.values())
            adicionados = 0
            for tag, valor in novos:
                if valor not in store.get(tag, set()):
                    adicionados += 1
            total_proposto = total_atual + adicionados

            if total_proposto > limite:
                tag_dominante = (
                    max(store.items(), key=lambda x: len(x[1]))[0]
                    if store else novos[0][0]
                )
                # NAO muta — store fica intacto.
                return False, tag_dominante, total_proposto

            for tag, valor in novos:
                store[tag].add(valor)
            return True, None, total_proposto

    def total_para_site(self, site_id: str) -> int:
        with self._lock:
            return sum(len(s) for s in self._stores.get(site_id, {}).values())

    def alerta_pendente(self, site_id: str, limite: int) -> Optional[int]:
        """Retorna 80 ou 95 se cardinalidade cruzou esse threshold e ainda
        nao foi alertado. Marca como emitido pra nao repetir.

        Niveis sao consumidos um por chamada (95 antes de 80). Retorna None
        quando nada novo a alertar.
        """
        if not site_id or limite <= 0:
            return None
        with self._lock:
            total = sum(len(s) for s in self._stores.get(site_id, {}).values())
            pct = (total / limite) * 100
            ja_emitidos = self._alertas_emitidos[site_id]
            for nivel in self._NIVEIS_ALERTA:
                if pct >= nivel and nivel not in ja_emitidos:
                    ja_emitidos.add(nivel)
                    return nivel
        return None

    def por_tag(self, site_id: str) -> Dict[str, int]:
        """Snapshot de |set| por tag. Util para diagnostico e tests."""
        with self._lock:
            store = self._stores.get(site_id, {})
            return {tag: len(valores) for tag, valores in store.items()}

    def invalidar_site(self, site_id: str) -> None:
        with self._lock:
            self._stores.pop(site_id, None)
            self._alertas_emitidos.pop(site_id, None)

    def limpar(self) -> None:
        with self._lock:
            self._stores.clear()
            self._alertas_emitidos.clear()


_tracker_global: Optional[TrackerCardinalidade] = None


def obter_tracker() -> TrackerCardinalidade:
    global _tracker_global
    if _tracker_global is None:
        _tracker_global = TrackerCardinalidade()
    return _tracker_global


def resetar_tracker() -> None:
    """Apenas para testes."""
    global _tracker_global
    _tracker_global = None
