"""Helper de logs estruturados para a camada de analytics.

Formato: `evento=<nome> chave=valor chave=valor ...`. Cada evento carrega
`session_id`, `id_registro` e `app_id` (quando disponiveis) para permitir
correlacao entre etapas de uma mesma ingestao.
"""
import logging
from typing import Any


def formatar_evento(evento: str, **campos: Any) -> str:
    partes = [f'evento={evento}']
    for chave, valor in campos.items():
        if valor is None:
            continue
        partes.append(f'{chave}={valor}')
    return ' '.join(partes)


def emitir_log(logger: logging.Logger, nivel: int, evento: str, **campos: Any) -> None:
    logger.log(nivel, formatar_evento(evento, **campos))
