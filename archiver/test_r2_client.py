"""TDD do R2Client.

R2 e S3-compatible — `boto3` aponta pro endpoint `*.r2.cloudflarestorage.com`
e o resto e identico. `moto` mocka S3 em memoria, suficiente pra validar:
- Upload em key correta `<slug>/<YYYY>/<MM>/<DD>.lp.gz`
- Content-Type + Content-Encoding corretos pra browser baixar e ja descompactar
- Geracao de presigned GET URL com TTL configuravel
"""
import os
import sys
import unittest
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

import boto3
from moto import mock_aws

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archiver.r2_client import R2Client


_BUCKET = 'dsplayground-analytics-archive'


def _criar_bucket(client):
    """Helper — moto exige bucket existir antes de PUT."""
    client.create_bucket(Bucket=_BUCKET)


@mock_aws
class R2ClientTest(unittest.TestCase):

    def setUp(self):
        # boto3 client interno do moto pra preparar bucket + inspecionar
        # us-east-1 evita LocationConstraint exigido por moto pra outras regions.
        self._s3 = boto3.client(
            's3',
            region_name='us-east-1',
            aws_access_key_id='AKIAIOSFODNN7EXAMPLEKEYABCDEFGHI', aws_secret_access_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
        )
        _criar_bucket(self._s3)

        # SUT — endpoint_url=None usa boto3 default (AWS), interceptado por moto.
        # Em prod o caller passa R2Client.endpoint_padrao_r2(account_id).
        self.r2 = R2Client(
            access_key_id='AKIAIOSFODNN7EXAMPLEKEYABCDEFGHI',
            secret_access_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
            bucket=_BUCKET,
            endpoint_url=None,
        )

    def test_upload_grava_em_key_canonica_slug_yyyy_mm_dd(self):
        body = b'\x1f\x8b\x08\x00fake gzip body'  # bytes arbitrarios
        url = self.r2.upload(slug='acme-test', dia=date(2026, 4, 30), body=body)

        # PUT aconteceu — confirma via HeadObject
        head = self._s3.head_object(
            Bucket=_BUCKET,
            Key='acme-test/2026/04/30.lp.gz',
        )
        self.assertEqual(head['ContentLength'], len(body))
        self.assertEqual(head['ContentType'], 'application/octet-stream')
        self.assertEqual(head['ContentEncoding'], 'gzip')

        # upload retorna a key (caller pode logar/persistir)
        self.assertEqual(url, 'acme-test/2026/04/30.lp.gz')

    def test_upload_overwrite_idempotente(self):
        # Cron pode rodar duas vezes pro mesmo dia (manual + auto).
        # PUT em S3 e overwrite por padrao — esse comportamento e OK aqui.
        self.r2.upload(slug='x', dia=date(2026, 4, 30), body=b'primeiro')
        self.r2.upload(slug='x', dia=date(2026, 4, 30), body=b'segundo overwrite')

        obj = self._s3.get_object(Bucket=_BUCKET, Key='x/2026/04/30.lp.gz')
        self.assertEqual(obj['Body'].read(), b'segundo overwrite')

    def test_listar_arquivos_do_slug_retorna_keys_em_ordem_cronologica(self):
        self.r2.upload(slug='cli', dia=date(2026, 4, 30), body=b'a')
        self.r2.upload(slug='cli', dia=date(2026, 5, 1), body=b'b')
        self.r2.upload(slug='outro', dia=date(2026, 4, 30), body=b'c')

        keys = self.r2.listar_arquivos_do_slug('cli')

        self.assertEqual(keys, [
            'cli/2026/04/30.lp.gz',
            'cli/2026/05/01.lp.gz',
        ])

    def test_listar_arquivos_de_slug_inexistente_retorna_lista_vazia(self):
        keys = self.r2.listar_arquivos_do_slug('nao-existe')
        self.assertEqual(keys, [])

    def test_signed_url_para_download_tem_ttl_configuravel(self):
        self.r2.upload(slug='cli', dia=date(2026, 4, 30), body=b'data')

        url = self.r2.signed_url_para_download(
            key='cli/2026/04/30.lp.gz',
            ttl_segundos=300,
        )

        self.assertTrue(url.startswith('http'))
        # Presigned URL inclui X-Amz-Expires (em segundos)
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs.get('X-Amz-Expires'), ['300'])
        self.assertIn('cli/2026/04/30.lp.gz', url)


if __name__ == '__main__':
    unittest.main()
