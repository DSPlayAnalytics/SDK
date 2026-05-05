"""CLI para configurar retencao do bucket de analytics no InfluxDB.

Uso:
    python scripts/configurar_retencao.py --dias 90
    python scripts/configurar_retencao.py --dias 90 --bucket portifolio_prod

Se `--bucket` nao for informado, usa o configurado em `config.py`.
Requer `INFLUXDB_TOKEN` com permissao de `buckets:write`.
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from influxdb_client import InfluxDBClient, BucketRetentionRules  # noqa: E402
from config import config  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Configura retencao do bucket de analytics.')
    parser.add_argument('--dias', type=int, required=True, help='Dias de retencao (ex.: 90).')
    parser.add_argument('--bucket', default=None, help='Nome do bucket. Default: config.py.')
    args = parser.parse_args(argv)

    config_name = os.environ.get('FLASK_ENV', 'development')
    app_config = config.get(config_name, config['default'])()

    bucket_nome = args.bucket or app_config.INFLUXDB_BUCKET
    segundos = args.dias * 24 * 60 * 60

    print(f'Configurando retencao de {args.dias} dias no bucket "{bucket_nome}"...')

    client = InfluxDBClient(
        url=app_config.INFLUXDB_URL,
        token=app_config.INFLUXDB_TOKEN,
        org=app_config.INFLUXDB_ORG,
    )
    try:
        buckets_api = client.buckets_api()
        bucket = buckets_api.find_bucket_by_name(bucket_nome)
        if not bucket:
            print(f'ERRO: bucket "{bucket_nome}" nao encontrado.', file=sys.stderr)
            return 1

        bucket.retention_rules = [BucketRetentionRules(type='expire', every_seconds=segundos)]
        buckets_api.update_bucket(bucket=bucket)
        print(f'OK: bucket "{bucket_nome}" com retencao de {args.dias} dias aplicada.')
        return 0
    finally:
        client.close()


if __name__ == '__main__':
    sys.exit(main())
