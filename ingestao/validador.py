"""Valida payloads `analytics_data` antes da transformacao em metricas.

Retorna `(ok, erros)` onde `erros` e uma lista de caminhos pontuando o local
de cada problema (ex.: `paginas./[0].eventos[2].tipo`). Campos desconhecidos
no envelope e em cada evento sao ignorados silenciosamente para preservar
forward-compat do contrato.
"""
import re
from typing import Any, List, Tuple

TIPOS_EVENTO_VALIDOS = frozenset({
    'page_view',
    'page_exit',
    'click',
    'touch',
    'scroll_depth',
    'mouse_move',
    'hover',
    'element_exposure',
    'web_vital',
    'custom',
})

# Schema 1.2 (SDK v0.4): user_id / group_id opcionais. Charset estreito
# pra evitar log injection (\n) e ambiguidade em queries Flux. `@` aceito
# pra cliente poder mandar email hasheado-parcial sem reescrever.
_LIMITE_ID = 256
_RE_ID_OPACO = re.compile(r"^[A-Za-z0-9_\-:.@]+$")


AMBIENTES_VALIDOS = frozenset({'development', 'test', 'staging', 'production'})


def validar_payload(data: Any) -> Tuple[bool, List[str]]:
    if not isinstance(data, dict):
        return False, ['payload']

    erros: List[str] = []

    _validar_string_obrigatoria(data, 'id_registro', erros)
    _validar_string_obrigatoria(data, 'app_id', erros)
    _validar_ambiente(data, erros)
    _validar_numero_obrigatorio(data, 'timestamp_inicial', erros)
    _validar_numero_obrigatorio(data, 'timestamp_final', erros)
    _validar_paginas(data.get('paginas'), erros)
    _validar_id_opcional(data, 'user_id', erros)
    _validar_id_opcional(data, 'group_id', erros)

    return (len(erros) == 0, erros)


def _validar_id_opcional(data: dict, chave: str, erros: List[str]) -> None:
    """Schema 1.2: aceita ausente ou null. Se presente, exige string opaca
    com charset estreito e <=256 chars."""
    if chave not in data:
        return
    valor = data[chave]
    if valor is None:
        return
    if not isinstance(valor, str):
        erros.append(chave)
        return
    if not valor or len(valor) > _LIMITE_ID:
        erros.append(chave)
        return
    if not _RE_ID_OPACO.match(valor):
        erros.append(chave)


def _validar_string_obrigatoria(data: dict, chave: str, erros: List[str]) -> None:
    valor = data.get(chave)
    if not isinstance(valor, str) or not valor:
        erros.append(chave)


def _validar_numero_obrigatorio(data: dict, chave: str, erros: List[str]) -> None:
    if chave not in data:
        erros.append(chave)
        return
    valor = data[chave]
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        erros.append(chave)


def _validar_ambiente(data: dict, erros: List[str]) -> None:
    valor = data.get('ambiente')
    if not isinstance(valor, str) or valor not in AMBIENTES_VALIDOS:
        erros.append('ambiente')


def _validar_paginas(paginas: Any, erros: List[str]) -> None:
    if paginas is None:
        erros.append('paginas')
        return
    if not isinstance(paginas, dict):
        erros.append('paginas')
        return

    for page_id, lista in paginas.items():
        prefixo = f'paginas.{page_id}'
        if not isinstance(lista, list):
            erros.append(prefixo)
            continue
        for idx, pagina in enumerate(lista):
            caminho = f'{prefixo}[{idx}]'
            if not isinstance(pagina, dict):
                erros.append(caminho)
                continue
            _validar_pagina(pagina, caminho, erros)


def _validar_pagina(pagina: dict, caminho: str, erros: List[str]) -> None:
    eventos = pagina.get('eventos', [])
    if not isinstance(eventos, list):
        erros.append(f'{caminho}.eventos')
        return
    for idx, evento in enumerate(eventos):
        caminho_evento = f'{caminho}.eventos[{idx}]'
        if not isinstance(evento, dict):
            erros.append(caminho_evento)
            continue
        _validar_evento(evento, caminho_evento, erros)


def _validar_evento(evento: dict, caminho: str, erros: List[str]) -> None:
    tipo = evento.get('tipo')
    if tipo not in TIPOS_EVENTO_VALIDOS:
        erros.append(f'{caminho}.tipo')

    timestamp = evento.get('timestamp')
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        erros.append(f'{caminho}.timestamp')
