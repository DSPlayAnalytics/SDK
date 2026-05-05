"""Re-importa dashboards out-of-the-box pra um cliente JA provisionado.

Uso quando JSON dos dashboards muda em `ark/monitoring/dashboards/` e
clientes existentes precisam pegar a versao nova (ex: novos quick-links
no topo, painel novo, query corrigida).

NAO toca em sites/buckets/datasources/tokens — assume tudo ja existe.
Falha cedo se cliente nao foi provisionado antes.

Uso:
  docker compose exec backend python scripts/redo_dashboards.py --slug acme-test
  docker compose exec backend python scripts/redo_dashboards.py --slug acme-test --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.tenants_repo import criar_tenants_repo  # noqa: E402
from config import config  # noqa: E402
from integrations.grafana_client import GrafanaClient  # noqa: E402

# Reusa o helper interno do provisionar_cliente — exato mesmo path de import,
# mesma logica de overwrite. Single source of truth.
from scripts.provisionar_cliente import _provisionar_dashboards  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-importa dashboards do cliente (sem mexer em site/bucket/token).",
    )
    parser.add_argument("--slug", required=True,
                        help="Slug do cliente ja provisionado (ex: acme-test)")
    parser.add_argument("--json", action="store_true", help="Saida JSON")
    args = parser.parse_args(argv)

    cfg_name = os.environ.get("FLASK_ENV", "development")
    cfg = config[cfg_name]

    # 1) Confirma que o site existe
    repo = criar_tenants_repo(cfg.TENANTS_DATABASE_URL)
    site = repo.obter_site_por_slug(args.slug)
    if site is None:
        print(f"erro: site '{args.slug}' nao encontrado em sites — provisione antes",
              file=sys.stderr)
        return 1
    bucket_name = site.bucket_name or f"cliente_{args.slug}"

    # 2) Conecta no Grafana
    grafana_url = os.environ.get("GRAFANA_URL", "http://localhost:3001")
    gf = GrafanaClient(
        grafana_url,
        os.environ.get("GRAFANA_ADMIN_USER", "admin"),
        os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin"),
    )

    # 3) Pega org existente do cliente (idempotente — nao recria)
    org_name = f"cliente_{args.slug}"
    try:
        org_id = gf.get_or_create_org(org_name)
    except RuntimeError as erro:
        print(f"erro Grafana org: {erro}", file=sys.stderr)
        return 2

    # 4) Pega datasource existente — _provisionar_dashboards substitui
    # __DATASOURCE_UID__ no JSON. Sem ds existente, dashboard imports OK
    # mas as queries quebram. Falha cedo.
    ds_name = f"influxdb_{args.slug}"
    ds = gf.get_datasource_by_name(ds_name, org_id=org_id)
    if ds is None:
        print(f"erro: datasource '{ds_name}' nao existe na org {org_name} — "
              f"rode provisionar_cliente.py primeiro", file=sys.stderr)
        return 3
    ds_uid = ds.get("uid", "")

    # 5) Re-importa dashboards
    dashboards = _provisionar_dashboards(
        gf, org_id=org_id, slug=args.slug,
        bucket_name=bucket_name, datasource_uid=ds_uid,
    )

    # Output
    if args.json:
        print(json.dumps({
            "slug": args.slug,
            "org_id": org_id,
            "datasource_uid": ds_uid,
            "dashboards": dashboards,
        }, indent=2))
        return 0

    print(f"== Dashboards re-importados pra '{args.slug}' ==")
    print(f"  org           : {org_name} (id={org_id})")
    print(f"  datasource    : {ds_name} (uid={ds_uid})")
    print(f"  dashboards    : {len(dashboards)}")
    for d in dashboards:
        print(f"    - {d['arquivo']}: uid={d['uid']} v{d['version']} {d.get('url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
