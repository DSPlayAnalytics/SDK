"""R2Client — wrapper boto3 sobre Cloudflare R2 (S3-compatible).

R2 nao tem regions. boto3 exige `region_name` mas qualquer string serve. Usamos
'auto' por convencao da CF docs.

Decisoes de schema das keys: `<slug>/<YYYY>/<MM>/<DD>.lp.gz`
- Prefix por slug: `list_objects_v2(Prefix='<slug>/')` retorna so do cliente —
  importante pro endpoint /cliente/exportar nao vazar dados entre tenants.
- Sub-pastas YYYY/MM: lifecycle rule do R2 pode aplicar TTL por prefixo
  (ex: deletar everything older than 12mo) sem custo de listagem.

Content-Type=application/octet-stream + Content-Encoding=gzip pra browser
descompactar transparentemente em GET, mas curl -O salvar como `.lp.gz`.
"""
import logging
from datetime import date
from typing import List, Optional

import boto3
from botocore.client import Config

logger = logging.getLogger(__name__)

# R2 retorna versionId vazio em CompleteMultipartUpload — boto3 reclama em
# debug logging. Path-style addressing tambem e mandatorio (R2 nao suporta
# virtual-hosted-style fora dos custom domains).
_BOTO_CONFIG = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'},
    retries={'mode': 'standard', 'max_attempts': 3},
)


def _key_diaria(slug: str, dia: date) -> str:
    return f'{slug}/{dia.strftime("%Y/%m/%d")}.lp.gz'


class R2Client:
    """Cliente fino. Cada metodo encapsula 1 operacao S3 com defaults sensatos."""

    @staticmethod
    def endpoint_padrao_r2(account_id: str) -> str:
        """Default em prod: `https://<account_id>.r2.cloudflarestorage.com`.

        Caller pode passar isso pro construtor; em testes prefira `endpoint_url=None`
        (boto3 escolhe AWS default que moto intercepta) ou um endpoint local.
        """
        return f'https://{account_id}.r2.cloudflarestorage.com'

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        endpoint_url: Optional[str] = None,
    ):
        self._bucket = bucket
        self._endpoint = endpoint_url

        self._s3 = boto3.client(
            's3',
            endpoint_url=endpoint_url,  # None = boto3 default (AWS); moto intercepta
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name='auto' if endpoint_url else 'us-east-1',
            config=_BOTO_CONFIG,
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def upload(self, slug: str, dia: date, body: bytes) -> str:
        """PUT do gzip diario. Retorna a key (sem schema/host).

        Idempotente — overwrite e o comportamento default de S3.
        """
        key = _key_diaria(slug, dia)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType='application/octet-stream',
            ContentEncoding='gzip',
        )
        logger.info(
            f'evento=archive_upload bucket={self._bucket} key={key} '
            f'bytes={len(body)} slug={slug}'
        )
        return key

    def listar_arquivos_do_slug(self, slug: str) -> List[str]:
        """Lista keys do slug em ordem cronologica (lex == cronol pro schema YYYY/MM/DD)."""
        prefix = f'{slug}/'
        keys: List[str] = []
        continuation: Optional[str] = None
        while True:
            kwargs = {'Bucket': self._bucket, 'Prefix': prefix}
            if continuation:
                kwargs['ContinuationToken'] = continuation
            resp = self._s3.list_objects_v2(**kwargs)
            for item in resp.get('Contents', []):
                keys.append(item['Key'])
            if not resp.get('IsTruncated'):
                break
            continuation = resp.get('NextContinuationToken')
        keys.sort()
        return keys

    def signed_url_para_download(self, key: str, ttl_segundos: int = 300) -> str:
        """Presigned GET URL com TTL. Caller usa em redirect 302."""
        return self._s3.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': self._bucket, 'Key': key},
            ExpiresIn=ttl_segundos,
        )
