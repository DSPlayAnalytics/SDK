"""TDD do ArchiverService.export_window.

Cenario: dado um InfluxDB com pontos de 3 measurements (page_analytics,
web_vitals, custom_events) na janela [start, end], export_window retorna
bytes gzipados contendo line protocol de todos os pontos.

Mock injetado via construtor (DI explicita) — ArchiverService nao instancia
InfluxDBClient direto. Isso permite testar sem dependencia externa.
"""
import gzip
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archiver.service import ArchiverService


def _fake_record(measurement, values, time_iso):
    """Mimica influxdb_client.client.flux_table.FluxRecord."""
    rec = MagicMock()
    rec.get_measurement.return_value = measurement
    rec.values = values  # dict-like com tags + fields + _time
    rec.get_time.return_value = datetime.fromisoformat(time_iso.replace('Z', '+00:00'))
    return rec


def _fake_table(records):
    table = MagicMock()
    table.records = records
    return table


class ArchiverServiceTest(unittest.TestCase):

    def test_export_window_retorna_gzip_de_line_protocol_dos_3_measurements(self):
        # Arrange — Influx mock devolvendo 3 pontos (1 por measurement)
        page_record = _fake_record(
            'page_analytics',
            {
                # tags
                'session_id': 'sess-1', 'page_type': '/home', 'app_id': 'acme',
                'ambiente': 'production', 'device_type': 'desktop',
                # fields
                'cliques': 2, 'visualizacoes': 1, 'permanencia_segundos': 8.5,
                # InfluxDB sempre devolve _time + _measurement em values
                '_time': '2026-04-30T12:00:00Z', '_measurement': 'page_analytics',
            },
            '2026-04-30T12:00:00Z',
        )
        vital_record = _fake_record(
            'web_vitals',
            {
                'session_id': 'sess-1', 'page_type': '/home', 'nome': 'LCP',
                'rating': 'good', 'app_id': 'acme', 'ambiente': 'production',
                'valor': 1800.0,
                '_time': '2026-04-30T12:00:01Z', '_measurement': 'web_vitals',
            },
            '2026-04-30T12:00:01Z',
        )
        custom_record = _fake_record(
            'custom_events',
            {
                'session_id': 'sess-1', 'page_type': '/home', 'nome': 'checkout_iniciado',
                'app_id': 'acme', 'ambiente': 'production',
                'ocorrencias': 1,
                '_time': '2026-04-30T12:00:02Z', '_measurement': 'custom_events',
            },
            '2026-04-30T12:00:02Z',
        )

        client = MagicMock()
        client.query_api.return_value.query.return_value = [
            _fake_table([page_record, vital_record, custom_record]),
        ]

        service = ArchiverService(influx_client=client, org='zen')

        # Act
        result = service.export_window(
            slug='acme-test',
            start=datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
        )

        # Assert — bytes gzip
        self.assertIsInstance(result, bytes)
        self.assertEqual(result[:2], b'\x1f\x8b', "magic bytes de gzip")

        raw = gzip.decompress(result).decode('utf-8')
        # 3 linhas de line protocol (sem trailing empty)
        linhas = [l for l in raw.split('\n') if l.strip()]
        self.assertEqual(len(linhas), 3, f"esperado 3 linhas, recebi {len(linhas)}: {raw}")

        # cada linha bate o formato `<measurement>,<tags> <fields> <ns_timestamp>`
        self.assertTrue(any(l.startswith('page_analytics,') for l in linhas))
        self.assertTrue(any(l.startswith('web_vitals,') for l in linhas))
        self.assertTrue(any(l.startswith('custom_events,') for l in linhas))

        # tags presentes (ordem alfabetica esperada pra ser deterministico)
        page_line = next(l for l in linhas if l.startswith('page_analytics,'))
        self.assertIn('session_id=sess-1', page_line)
        self.assertIn('page_type=/home', page_line)
        # fields no formato Influx (int sem aspas, float sem aspas, string com aspas)
        self.assertIn('cliques=2i', page_line)
        self.assertIn('visualizacoes=1i', page_line)
        # timestamp em nanossegundos (Influx default precision)
        # 2026-04-30T12:00:00Z em ns since epoch
        ts_esperado = int(datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp() * 1_000_000_000)
        self.assertTrue(page_line.endswith(f' {ts_esperado}'),
                        f"timestamp ns invalido: {page_line}")

    def test_export_window_query_usa_bucket_correto_do_slug(self):
        client = MagicMock()
        client.query_api.return_value.query.return_value = []
        service = ArchiverService(influx_client=client, org='zen')

        service.export_window(
            slug='acme-test',
            start=datetime(2026, 4, 30, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )

        # Pegou bucket cliente_acme-test, nao default, nao errado
        chamada = client.query_api.return_value.query.call_args
        flux = chamada.kwargs.get('query') or (chamada.args[0] if chamada.args else '')
        self.assertIn('from(bucket: "cliente_acme-test")', flux)
        self.assertIn('2026-04-30T00:00:00+00:00', flux)
        self.assertIn('2026-05-01T00:00:00+00:00', flux)

    def test_export_window_bucket_vazio_retorna_gzip_de_string_vazia(self):
        # Quando nao ha pontos no range — ainda assim queremos um arquivo
        # (presenca do .gz no R2 e prova de que o cron rodou pra esse dia).
        client = MagicMock()
        client.query_api.return_value.query.return_value = []
        service = ArchiverService(influx_client=client, org='zen')

        result = service.export_window(
            slug='vazio',
            start=datetime(2026, 4, 30, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )

        self.assertIsInstance(result, bytes)
        self.assertEqual(result[:2], b'\x1f\x8b')
        self.assertEqual(gzip.decompress(result), b'')

    def test_export_window_escapa_virgulas_e_espacos_em_valores_de_tag(self):
        record = _fake_record(
            'custom_events',
            {
                'session_id': 'sess-1', 'page_type': '/home',
                'nome': 'evento, com virgula',  # tag value precisa escape
                'app_id': 'app com espaco',
                'ocorrencias': 1,
                '_time': '2026-04-30T12:00:00Z', '_measurement': 'custom_events',
            },
            '2026-04-30T12:00:00Z',
        )
        client = MagicMock()
        client.query_api.return_value.query.return_value = [_fake_table([record])]
        service = ArchiverService(influx_client=client, org='zen')

        result = service.export_window(
            slug='x',
            start=datetime(2026, 4, 30, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        raw = gzip.decompress(result).decode('utf-8')

        # virgula em tag value escapada com `\`
        self.assertIn(r'nome=evento\,\ com\ virgula', raw)
        self.assertIn(r'app_id=app\ com\ espaco', raw)


if __name__ == '__main__':
    unittest.main()
