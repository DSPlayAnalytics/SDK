"""CLI de administracao de tenants para o SDK de analytics.

Uso:
    python -m scripts.tenant_admin create --slug acme --nome "Acme" --ambiente production \
        --dominio https://acme.com --dominio https://www.acme.com
    python -m scripts.tenant_admin list
    python -m scripts.tenant_admin show --slug acme
    python -m scripts.tenant_admin revoke-key --key-id abc123
    python -m scripts.tenant_admin add-domain --slug acme --dominio https://nova.acme.com
    python -m scripts.tenant_admin set-quota --slug acme --eventos-por-dia 500000
    python -m scripts.tenant_admin cleanup-emissions --dias 7

O valor da publishable_key e exibido SOMENTE na criacao. Guarde com cuidado.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Garante importacao dos modulos do backend mesmo fora do Docker.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import config  # noqa: E402
from auth.tenants_repo import TenantsRepo, criar_tenants_repo  # noqa: E402


def _obter_repo() -> TenantsRepo:
    env = os.environ.get("FLASK_ENV", "development")
    cfg = config[env]
    return criar_tenants_repo(cfg.TENANTS_DATABASE_URL)


def cmd_create(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    existente = repo.obter_site_por_slug(args.slug)
    if existente:
        print(f"erro: slug '{args.slug}' ja existe (site_id={existente.id})", file=sys.stderr)
        return 1

    # Strict routing: todo site novo nasce com bucket_name preenchido. Sem isso,
    # ingest cai no bucket default e mistura tenants. provisionar_cliente.py
    # ainda eh quem cria o bucket no Influx; tenant_admin so registra o nome.
    bucket_name = args.bucket or f"cliente_{args.slug}"

    site = repo.criar_site(
        slug=args.slug,
        nome=args.nome,
        ambiente=args.ambiente,
        dominios=args.dominio or [],
        plano=args.plano,
        bucket_name=bucket_name,
    )
    _, valor = repo.criar_publishable_key(
        site_id=site.id, ambiente=args.ambiente, nome="default"
    )
    print(f"site criado: id={site.id} slug={site.slug} ambiente={site.ambiente}")
    print(f"bucket_name reservado: {bucket_name}")
    print(f"dominios permitidos: {', '.join(args.dominio) if args.dominio else '(nenhum)'}")
    print("publishable_key (guarde agora, nao sera exibida novamente):")
    print(f"  {valor}")
    print("AVISO: o bucket Influx ainda nao existe. Rode:")
    print(f"  python -m scripts.provisionar_cliente --slug {args.slug} "
          f"--nome '{args.nome}' --ambiente {args.ambiente} --plano {args.plano}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    repo = _obter_repo()
    sites = repo.listar_sites()
    if not sites:
        print("(nenhum site cadastrado)")
        return 0
    print(f"{'slug':<20} {'ambiente':<12} {'plano':<10} {'status':<10} id")
    for s in sites:
        print(f"{s.slug:<20} {s.ambiente:<12} {s.plano:<10} {s.status:<10} {s.id}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    site = repo.obter_site_por_slug(args.slug)
    if not site:
        print(f"erro: slug '{args.slug}' nao encontrado", file=sys.stderr)
        return 1
    dominios = repo.listar_dominios(site.id)
    keys = repo.listar_publishable_keys(site.id)
    quota = repo.obter_quota(site.id)
    consumo = repo.consumo_hoje(site.id)

    print(f"id:        {site.id}")
    print(f"slug:      {site.slug}")
    print(f"nome:      {site.nome}")
    print(f"ambiente:  {site.ambiente}")
    print(f"plano:     {site.plano}")
    print(f"status:    {site.status}")
    print(f"dominios:  {', '.join(dominios) if dominios else '(nenhum)'}")
    print(f"quota:     eventos/min={quota.eventos_por_minuto} eventos/dia={quota.eventos_por_dia} "
          f"emissoes_jwt/min={quota.emissoes_jwt_por_minuto} retencao_dias={quota.retencao_dias}")
    print(f"consumo hoje: {consumo}")
    print("publishable_keys:")
    if not keys:
        print("  (nenhuma)")
    else:
        for k in keys:
            marcador = "[revogada]" if k.revogada else "[ativa]   "
            print(f"  {marcador} key_id={k.key_id} nome={k.nome or '-'}")
    return 0


def cmd_revoke_key(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    repo.revogar_publishable_key(args.key_id)
    print(f"publishable_key revogada: {args.key_id}")
    return 0


def cmd_create_key(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    site = repo.obter_site_por_slug(args.slug)
    if not site:
        print(f"erro: slug '{args.slug}' nao encontrado", file=sys.stderr)
        return 1
    _, valor = repo.criar_publishable_key(
        site_id=site.id, ambiente=site.ambiente, nome=args.nome
    )
    print("nova publishable_key (guarde agora):")
    print(f"  {valor}")
    return 0


def cmd_add_domain(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    site = repo.obter_site_por_slug(args.slug)
    if not site:
        print(f"erro: slug '{args.slug}' nao encontrado", file=sys.stderr)
        return 1
    repo.adicionar_dominio(site.id, args.dominio)
    print(f"dominio adicionado a {args.slug}: {args.dominio}")
    return 0


def cmd_remove_domain(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    site = repo.obter_site_por_slug(args.slug)
    if not site:
        print(f"erro: slug '{args.slug}' nao encontrado", file=sys.stderr)
        return 1
    repo.remover_dominio(site.id, args.dominio)
    print(f"dominio removido de {args.slug}: {args.dominio}")
    return 0


def cmd_set_quota(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    site = repo.obter_site_por_slug(args.slug)
    if not site:
        print(f"erro: slug '{args.slug}' nao encontrado", file=sys.stderr)
        return 1
    repo.atualizar_quota(
        site.id,
        eventos_por_minuto=args.eventos_por_minuto,
        eventos_por_dia=args.eventos_por_dia,
        emissoes_jwt_por_minuto=args.emissoes_jwt_por_minuto,
        retencao_dias=args.retencao_dias,
    )
    print(f"quota atualizada para {args.slug}")
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    site = repo.obter_site_por_slug(args.slug)
    if not site:
        print(f"erro: slug '{args.slug}' nao encontrado", file=sys.stderr)
        return 1
    repo.atualizar_status_site(site.id, args.status)
    print(f"status de {args.slug} definido para {args.status}")
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    repo = _obter_repo()
    removidos = repo.limpar_emissoes_antigas(dias=args.dias)
    print(f"emissoes removidas: {removidos} (janela {args.dias} dias)")
    return 0


def cmd_backfill_buckets(args: argparse.Namespace) -> int:
    """Define bucket_name=cliente_<slug> para sites antigos sem bucket.

    Ainda nao cria o bucket no Influx — apenas registra no Postgres. O
    provisionar_cliente.py precisa ser rodado depois para materializar.
    """
    repo = _obter_repo()
    afetados = []
    for site in repo.listar_sites():
        if not site.bucket_name:
            bucket_name = f"cliente_{site.slug}"
            if args.dry_run:
                print(f"[dry-run] {site.slug}: would set bucket_name={bucket_name}")
            else:
                repo.definir_bucket_name(site.id, bucket_name)
                print(f"{site.slug}: bucket_name={bucket_name}")
            afetados.append(site.slug)
    if not afetados:
        print("(nenhum site precisa de backfill)")
    elif not args.dry_run:
        print(f"\n{len(afetados)} site(s) atualizados. Provisione cada um com:")
        for slug in afetados:
            print(f"  python -m scripts.provisionar_cliente --slug {slug} ...")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Administracao de tenants do SDK")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_create = sub.add_parser("create", help="Cria um novo site com publishable_key default")
    p_create.add_argument("--slug", required=True)
    p_create.add_argument("--nome", required=True)
    p_create.add_argument("--ambiente", required=True,
                          choices=["development", "test", "staging", "production"])
    p_create.add_argument("--dominio", action="append",
                          help="URL raiz permitida. Pode repetir.")
    p_create.add_argument("--plano", default="free")
    p_create.add_argument("--bucket", default=None,
                          help="Override do bucket_name (default: cliente_<slug>).")
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="Lista sites cadastrados")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Detalhes de um site")
    p_show.add_argument("--slug", required=True)
    p_show.set_defaults(func=cmd_show)

    p_revoke = sub.add_parser("revoke-key", help="Revoga uma publishable_key pelo key_id")
    p_revoke.add_argument("--key-id", required=True)
    p_revoke.set_defaults(func=cmd_revoke_key)

    p_create_key = sub.add_parser("create-key", help="Cria outra publishable_key para o site")
    p_create_key.add_argument("--slug", required=True)
    p_create_key.add_argument("--nome", default=None)
    p_create_key.set_defaults(func=cmd_create_key)

    p_add = sub.add_parser("add-domain", help="Adiciona dominio a allowlist do site")
    p_add.add_argument("--slug", required=True)
    p_add.add_argument("--dominio", required=True)
    p_add.set_defaults(func=cmd_add_domain)

    p_rm = sub.add_parser("remove-domain", help="Remove dominio da allowlist do site")
    p_rm.add_argument("--slug", required=True)
    p_rm.add_argument("--dominio", required=True)
    p_rm.set_defaults(func=cmd_remove_domain)

    p_quota = sub.add_parser("set-quota", help="Ajusta quotas do site")
    p_quota.add_argument("--slug", required=True)
    p_quota.add_argument("--eventos-por-minuto", type=int, dest="eventos_por_minuto")
    p_quota.add_argument("--eventos-por-dia", type=int, dest="eventos_por_dia")
    p_quota.add_argument("--emissoes-jwt-por-minuto", type=int, dest="emissoes_jwt_por_minuto")
    p_quota.add_argument("--retencao-dias", type=int, dest="retencao_dias")
    p_quota.set_defaults(func=cmd_set_quota)

    p_status = sub.add_parser("set-status", help="Suspende/bloqueia/reativa um site")
    p_status.add_argument("--slug", required=True)
    p_status.add_argument("--status", required=True,
                          choices=["ativo", "suspenso", "bloqueado"])
    p_status.set_defaults(func=cmd_set_status)

    p_clean = sub.add_parser("cleanup-emissions", help="Expurga log de emissoes antigas")
    p_clean.add_argument("--dias", type=int, default=7)
    p_clean.set_defaults(func=cmd_cleanup)

    p_backfill = sub.add_parser("backfill-buckets",
                                help="Define bucket_name=cliente_<slug> para sites antigos")
    p_backfill.add_argument("--dry-run", action="store_true",
                            help="Mostra o que faria sem alterar")
    p_backfill.set_defaults(func=cmd_backfill_buckets)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
