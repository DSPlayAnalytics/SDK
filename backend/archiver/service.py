r"""ArchiverService — exporta janelas pre-expiracao do InfluxDB como line protocol gzipado.

Decisoes:
- Linha por ponto, formato `<measurement>,<tags> <fields> <ns_timestamp>`
  (Influx line protocol v2). Re-importavel por `influx write` sem perda.
- Tags em ordem alfabetica por chave: deterministico (importante pra dedup
  e diff entre arquivos).
- Fields tipados explicitamente (`i` pra int, sufixo nenhum pra float, aspas
  pra string). Bool com `t/f`. NaN/None pula o field.
- Escape de tags conforme spec: virgula, igual e espaco viram `\,`, `\=`, `\ `.
"""
import gzip
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Tags conhecidas (ordem alfabetica e estatica garante deterministico). Qualquer
# campo NAO-listado em values vai pra fields. Mantido em sync com schema dos
# 3 measurements em ark/docs/dashboard-cliente.md secao 18 e
# influxdb_service.py:write_*.
_TAGS_CONHECIDAS = {
    'ambiente', 'app_id', 'device_type', 'ip_address', 'nome',
    'page_type', 'pais', 'rating', 'referrer_dominio', 'session_id',
}

# Chaves internas do InfluxDB que nao entram no line protocol.
_CHAVES_INTERNAS = {'_time', '_measurement', '_start', '_stop', '_field', '_value', 'result', 'table'}


def _escape_tag(s: str) -> str:
    """Escape de tag key/value: virgula, igual e espaco precisam `\\`."""
    return s.replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')


def _escape_string_field(s: str) -> str:
    """String field: envolver em aspas + escape de aspas e backslash."""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _format_field_value(v: Any) -> Optional[str]:
    """Renderiza um value como Influx field. None retorna None (skip)."""
    if v is None:
        return None
    if isinstance(v, bool):  # antes de int — bool e subclass de int em Python
        return 't' if v else 'f'
    if isinstance(v, int):
        return f'{v}i'
    if isinstance(v, float):
        return repr(v)  # repr pra preservar precisao
    if isinstance(v, str):
        return _escape_string_field(v)
    # fallback: stringifica
    return _escape_string_field(str(v))


def _ponto_para_line_protocol(measurement: str, values: Dict[str, Any], time_ns: int) -> Optional[str]:
    """Converte um ponto Flux pra uma linha de line protocol.

    Retorna None se nao houver field algum (Influx rejeita linhas sem fields).
    """
    tags: List[Tuple[str, str]] = []
    fields: List[Tuple[str, str]] = []

    for k, v in values.items():
        if k in _CHAVES_INTERNAS:
            continue
        if v is None:
            continue
        if k in _TAGS_CONHECIDAS:
            tags.append((k, _escape_tag(str(v))))
        else:
            formatted = _format_field_value(v)
            if formatted is not None:
                fields.append((_escape_tag(k), formatted))

    if not fields:
        return None

    # Ordem deterministica
    tags.sort(key=lambda kv: kv[0])
    fields.sort(key=lambda kv: kv[0])

    tags_str = ''.join(f',{k}={v}' for k, v in tags)
    fields_str = ','.join(f'{k}={v}' for k, v in fields)
    measurement_esc = _escape_tag(measurement)

    return f'{measurement_esc}{tags_str} {fields_str} {time_ns}'


class ArchiverService:
    """Exporta janelas temporais de um bucket Influx como line protocol gzip.

    Construido com DI explicita do client Influx pra facilitar mock em testes
    e permitir o caller controlar timeout/retries.
    """

    def __init__(self, influx_client, org: str):
        self._client = influx_client
        self._org = org

    def _query_flux(self, bucket: str, start: datetime, end: datetime) -> str:
        # `pivot` reconstroi a tabela larga (1 linha por ponto) que o `query()`
        # do influxdb_client aceita iterar com tags+fields no mesmo `values`.
        return f'''from(bucket: "{bucket}")
  |> range(start: {start.isoformat()}, stop: {end.isoformat()})
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''

    def export_window(self, slug: str, start: datetime, end: datetime) -> bytes:
        """Exporta [start, end) do bucket cliente_<slug> como line protocol gzip.

        Retorna sempre bytes — gzip de string vazia se nao ha pontos. O caller
        pode decidir se faz upload mesmo assim (presenca do arquivo prova que
        o cron rodou; ausencia indica falha de exportacao).
        """
        bucket = f'cliente_{slug}'
        flux = self._query_flux(bucket, start, end)

        try:
            tabelas = self._client.query_api().query(query=flux, org=self._org)
        except TypeError:
            # mock simples sem kwargs
            tabelas = self._client.query_api().query(flux)

        linhas: List[str] = []
        for tabela in tabelas:
            for record in tabela.records:
                measurement = record.get_measurement()
                values = dict(record.values)  # copia defensiva
                ts = record.get_time()
                if ts is None:
                    continue
                # nanoseconds since epoch (default Influx precision)
                time_ns = int(ts.timestamp() * 1_000_000_000)
                linha = _ponto_para_line_protocol(measurement, values, time_ns)
                if linha is not None:
                    linhas.append(linha)

        if not linhas:
            payload = b''
        else:
            payload = ('\n'.join(linhas) + '\n').encode('utf-8')

        return gzip.compress(payload, compresslevel=6, mtime=0)
