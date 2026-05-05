"""CLI idempotente que provisiona um cliente fim-a-fim:

  1. site no Postgres/SQLite (TenantsRepo) — cria se nao existir
  2. publishable_key default                  — cria se nao houver nenhuma ativa
  3. quotas + retencao_dias do plano          — atualiza
  4. bucket InfluxDB com retention            — cria ou atualiza
  5. token Influx escopado ao bucket (read)   — recria sempre (Grafana plaintext)
  6. organization no Grafana                  — cria se nao existir
  7. datasource Influx no Grafana             — cria/atualiza com novo token
  8. dashboards out-of-the-box                — importa de ark/monitoring/dashboards/
                                                substituindo __BUCKET__ pelo bucket do cliente

Uso (dentro de docker-compose ou com os envs equivalentes):

    python -m scripts.provisionar_cliente \
        --slug acme-test --nome "Acme Test" --ambiente development \
        --dominio https://acme.test --plano free

Envs requeridos:
    INFLUXDB_URL, INFLUXDB_ORG, INFLUXDB_TOKEN  (admin token)
    GRAFANA_URL                                  (ex.: http://grafana:3000)
    GRAFANA_ADMIN_USER, GRAFANA_ADMIN_PASSWORD   (admin Basic Auth)
    TENANTS_DATABASE_URL                          (Postgres ou SQLite)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.tenants_repo import TenantsRepo, criar_tenants_repo  # noqa: E402
from config import config  # noqa: E402
from integrations.grafana_client import GrafanaClient  # noqa: E402

from influxdb_client import (  # noqa: E402
    Authorization,
    BucketRetentionRules,
    InfluxDBClient,
    Permission,
    PermissionResource,
)


# Defaults por plano. Ver ark/docs/dashboard-cliente.md sec. 18.
PLANO_DEFAULTS = {
    "free":    {"retencao_dias":   7, "eventos_por_dia":    10_000, "eventos_por_minuto":   600},
    "pequeno": {"retencao_dias":  30, "eventos_por_dia":   100_000, "eventos_por_minuto":   600},
    "medio":   {"retencao_dias":  90, "eventos_por_dia": 1_000_000, "eventos_por_minuto":  6_000},
    "grande":  {"retencao_dias": 365, "eventos_por_dia":10_000_000, "eventos_por_minuto": 60_000},
}


@dataclass
class ProvisionResult:
    site_id: str
    slug: str
    plano: str
    bucket_name: str
    bucket_id: str
    retention_dias: int
    grafana_org_id: int
    grafana_org_name: str
    grafana_ds_uid: str
    grafana_ds_name: str
    influx_token_id: str
    influx_token_value: str
    publishable_key: Optional[str]
    dashboards: list[dict]


# Diretorio de templates de dashboard. Quando rodando no container backend,
# ark/ nao esta no bind-mount (so backend/ esta), entao o compose monta
# ./ark/monitoring/dashboards:/app/dashboards:ro e seta DASHBOARDS_TEMPLATE_DIR.
# Fora do container (host), cai no path relativo ao repo.
DASHBOARDS_DIR = Path(os.environ.get(
    "DASHBOARDS_TEMPLATE_DIR",
    str(BACKEND_DIR.parent / "ark" / "monitoring" / "dashboards"),
))


# ----------------------------- Postgres -----------------------------

def _ensure_site(repo: TenantsRepo, *, slug: str, nome: str, ambiente: str,
                 dominios: list[str], plano: str, bucket_name: str):
    site = repo.obter_site_por_slug(slug)
    publishable = None
    if site is None:
        site = repo.criar_site(slug=slug, nome=nome, ambiente=ambiente,
                               dominios=dominios, plano=plano, bucket_name=bucket_name)
        _, publishable = repo.criar_publishable_key(
            site_id=site.id, ambiente=ambiente, nome="default"
        )
    else:
        # Backfill do bucket_name se nao havia
        if not site.bucket_name:
            repo.definir_bucket_name(site.id, bucket_name)
        elif site.bucket_name != bucket_name:
            raise SystemExit(
                f"erro: site '{slug}' ja tem bucket_name='{site.bucket_name}', "
                f"diferente do solicitado '{bucket_name}'. "
                f"Para mudar bucket use --bucket explicitamente igual ao atual ou nao passe."
            )
        # Garante 1 publishable ativa; nao re-emite valor (so e visivel na criacao).
        keys = repo.listar_publishable_keys(site.id)
        if not any(not k.revogada for k in keys):
            _, publishable = repo.criar_publishable_key(
                site_id=site.id, ambiente=ambiente, nome="default"
            )

    # Aplica defaults do plano (sobrescreve quotas atuais)
    plano_cfg = PLANO_DEFAULTS.get(plano)
    if plano_cfg:
        repo.atualizar_quota(site.id, **plano_cfg)

    return site, publishable, plano_cfg


# ----------------------------- InfluxDB -----------------------------

def _ensure_bucket(client: InfluxDBClient, *, org_name: str, bucket_name: str,
                   retention_dias: int):
    org = _influx_org(client, org_name)
    buckets_api = client.buckets_api()
    bucket = buckets_api.find_bucket_by_name(bucket_name)
    every_seconds = retention_dias * 24 * 60 * 60
    rules = [BucketRetentionRules(type="expire", every_seconds=every_seconds)]
    if bucket is None:
        bucket = buckets_api.create_bucket(
            bucket_name=bucket_name,
            retention_rules=rules,
            org_id=org.id,
            description=f"bucket dedicado para cliente_slug={bucket_name}",
        )
        return bucket, org
    # idempotente: ajusta retencao se mudou
    if not bucket.retention_rules or bucket.retention_rules[0].every_seconds != every_seconds:
        bucket.retention_rules = rules
        bucket = buckets_api.update_bucket(bucket=bucket)
    return bucket, org


def _rotate_grafana_read_token(client: InfluxDBClient, *, org_id: str, bucket_id: str,
                               descricao: str):
    """Recria token escopado: plaintext so e visivel no momento da criacao."""
    auths_api = client.authorizations_api()
    # Revoga tokens antigos com mesma descricao.
    existentes = auths_api.find_authorizations(org_id=org_id) or []
    for a in existentes:
        if (a.description or "") == descricao:
            try:
                auths_api.delete_authorization(a)
            except Exception as exc:
                print(f"warn: falha ao deletar token antigo {a.id}: {exc}", file=sys.stderr)

    permissions = [
        Permission(action="read", resource=PermissionResource(
            type="buckets", id=bucket_id, org_id=org_id)),
    ]
    nova = auths_api.create_authorization(authorization=Authorization(
        org_id=org_id, permissions=permissions, description=descricao,
    ))
    return nova


def _influx_org(client: InfluxDBClient, org_name: str):
    orgs = client.organizations_api().find_organizations(org=org_name)
    if not orgs:
        raise SystemExit(f"erro: organizacao Influx '{org_name}' nao encontrada")
    return orgs[0]


# ----------------------------- Grafana -----------------------------
# GrafanaClient lifted para backend/integrations/grafana_client.py — compartilhado
# com auth/grafana_sync.py. Se chamadas falharem aqui, queremos SystemExit
# (script falha). Se falharem no sync runtime, queremos best-effort. Por isso
# wrappers locais que convertem RuntimeError do client em SystemExit.


# ----------------------------- Dashboards -----------------------------

def _carregar_template(arquivo: Path, bucket_name: str,
                       datasource_uid: str = "") -> dict:
    """Le JSON do disco e substitui placeholders.

    Substituicoes:
      __BUCKET__         -> bucket_name (cliente_<slug>)
      __DATASOURCE_UID__ -> uid do datasource Influx criado pra esse cliente

    O datasource_uid eh critico: sem uid explicito por painel, Grafana 11.2
    pode resolver o `"datasource": {"type": "influxdb"}` para o plugin de
    testdata e mostrar valores aleatorios em vez de "No data".
    """
    raw = arquivo.read_text(encoding="utf-8")
    raw = raw.replace("__BUCKET__", bucket_name)
    raw = raw.replace("__DATASOURCE_UID__", datasource_uid)
    try:
        dashboard = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"erro: template '{arquivo.name}' tem JSON invalido: {exc}")
    # Reset de id evita conflito quando o mesmo UID existe em outra org.
    dashboard["id"] = None
    return dashboard


def _provisionar_dashboards(gf: GrafanaClient, *, org_id: int, slug: str,
                            bucket_name: str,
                            datasource_uid: str = "") -> list[dict]:
    """Importa todos os JSONs de dashboards/ na org do cliente.

    Idempotente: cada JSON tem `uid` fixo; overwrite=True faz versao++.
    """
    if not DASHBOARDS_DIR.exists():
        print(f"warn: pasta {DASHBOARDS_DIR} nao existe, pulando dashboards", file=sys.stderr)
        return []

    importados = []
    for template in sorted(DASHBOARDS_DIR.glob("*.json")):
        dashboard = _carregar_template(template, bucket_name,
                                       datasource_uid=datasource_uid)
        try:
            resp = gf.import_dashboard(
                org_id=org_id, dashboard=dashboard,
                message=f"provisionado para {slug} via provisionar_cliente.py",
            )
        except RuntimeError as erro:
            raise SystemExit(f"erro ao importar {template.name}: {erro}")
        importados.append({
            "arquivo": template.name,
            "uid": resp.get("uid"),
            "url": resp.get("url"),
            "version": resp.get("version"),
        })
    return importados


# ----------------------------- main flow -----------------------------

def provisionar(args: argparse.Namespace) -> ProvisionResult:
    cfg_name = os.environ.get("FLASK_ENV", "development")
    cfg = config[cfg_name]

    repo = criar_tenants_repo(cfg.TENANTS_DATABASE_URL)
    bucket_name = args.bucket or f"cliente_{args.slug}"

    site, publishable, plano_cfg = _ensure_site(
        repo,
        slug=args.slug, nome=args.nome, ambiente=args.ambiente,
        dominios=args.dominio or [], plano=args.plano,
        bucket_name=bucket_name,
    )

    retencao = (plano_cfg or {}).get("retencao_dias", 30)

    influx_url = os.environ.get("INFLUXDB_URL") or cfg.INFLUXDB_URL
    influx_token = os.environ.get("INFLUXDB_TOKEN") or cfg.INFLUXDB_TOKEN
    influx_org_name = os.environ.get("INFLUXDB_ORG") or cfg.INFLUXDB_ORG
    if not (influx_url and influx_token and influx_org_name):
        raise SystemExit("erro: INFLUXDB_URL/INFLUXDB_TOKEN/INFLUXDB_ORG nao configurados")

    with InfluxDBClient(url=influx_url, token=influx_token, org=influx_org_name) as ic:
        bucket, org = _ensure_bucket(ic, org_name=influx_org_name,
                                     bucket_name=bucket_name, retention_dias=retencao)
        token = _rotate_grafana_read_token(
            ic, org_id=org.id, bucket_id=bucket.id,
            descricao=f"cliente_{args.slug}_grafana_read",
        )

    grafana_url = os.environ.get("GRAFANA_URL", "http://localhost:3001")
    gf_user = os.environ.get("GRAFANA_ADMIN_USER", "admin")
    gf_pass = os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin")
    gf = GrafanaClient(grafana_url, gf_user, gf_pass)

    try:
        org_name = f"cliente_{args.slug}"
        gf_org_id = gf.get_or_create_org(org_name)
        ds_name = f"influxdb_{args.slug}"
        ds = gf.upsert_influx_datasource(
            org_id=gf_org_id, name=ds_name,
            influx_url=os.environ.get("INFLUXDB_URL_INTERNAL", influx_url),
            influx_org=influx_org_name, bucket=bucket_name, token=token.token,
        )
    except RuntimeError as erro:
        raise SystemExit(f"erro Grafana: {erro}")

    # Importa dashboards out-of-the-box. Skip via flag pra debug.
    dashboards = []
    if not args.skip_dashboards:
        dashboards = _provisionar_dashboards(
            gf, org_id=gf_org_id, slug=args.slug, bucket_name=bucket_name,
            datasource_uid=ds.get("uid", ""),
        )

    return ProvisionResult(
        site_id=site.id, slug=args.slug, plano=args.plano,
        bucket_name=bucket_name, bucket_id=bucket.id, retention_dias=retencao,
        grafana_org_id=gf_org_id, grafana_org_name=org_name,
        grafana_ds_uid=ds.get("uid", ""), grafana_ds_name=ds_name,
        influx_token_id=token.id, influx_token_value=token.token,
        publishable_key=publishable,
        dashboards=dashboards,
    )


def imprimir(result: ProvisionResult, *, json_out: bool):
    if json_out:
        print(json.dumps({
            "site_id": result.site_id, "slug": result.slug, "plano": result.plano,
            "bucket_name": result.bucket_name, "bucket_id": result.bucket_id,
            "retention_dias": result.retention_dias,
            "grafana_org_id": result.grafana_org_id,
            "grafana_org_name": result.grafana_org_name,
            "grafana_ds_uid": result.grafana_ds_uid,
            "grafana_ds_name": result.grafana_ds_name,
            "influx_token_id": result.influx_token_id,
            "publishable_key": result.publishable_key,
            "dashboards": result.dashboards,
        }, indent=2))
        return
    print("== Provisionamento concluido ==")
    print(f"  site_id        : {result.site_id}")
    print(f"  slug           : {result.slug}")
    print(f"  plano          : {result.plano}")
    print(f"  bucket_name    : {result.bucket_name}")
    print(f"  bucket_id      : {result.bucket_id}")
    print(f"  retention_dias : {result.retention_dias}")
    print(f"  grafana_org    : {result.grafana_org_name} (id={result.grafana_org_id})")
    print(f"  grafana_ds     : {result.grafana_ds_name} (uid={result.grafana_ds_uid})")
    print(f"  influx_token   : id={result.influx_token_id} (token nao reexibido)")
    if result.dashboards:
        print(f"  dashboards     :")
        for d in result.dashboards:
            print(f"    - {d['arquivo']}: uid={d['uid']} v{d['version']} {d.get('url', '')}")
    if result.publishable_key:
        print(f"  publishable_key (anote, nao sera reexibida):")
        print(f"    {result.publishable_key}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Provisiona cliente fim-a-fim (Postgres + Influx + Grafana)")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--nome", required=True)
    parser.add_argument("--ambiente", required=True,
                        choices=["development", "test", "staging", "production"])
    parser.add_argument("--dominio", action="append", help="URL raiz; pode repetir")
    parser.add_argument("--plano", default="free", choices=list(PLANO_DEFAULTS.keys()))
    parser.add_argument("--bucket", default=None,
                        help="Override do bucket (default: cliente_<slug>)")
    parser.add_argument("--skip-dashboards", action="store_true",
                        help="Nao importa dashboards (debug)")
    parser.add_argument("--json", action="store_true", help="Saida JSON")
    args = parser.parse_args(argv)

    result = provisionar(args)
    imprimir(result, json_out=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
