"""CLI para gerenciar usuarios humanos do dashboard self-service.

Uso (dentro do container backend):

    python scripts/dashboard_user_admin.py criar \\
        --site-slug acme-test \\
        --email dan@acme.test \\
        --senha secret-mvp-123 \\
        --papel admin \\
        --criar-site --site-nome "ACME Test" --site-dominio http://localhost:3000

    python scripts/dashboard_user_admin.py listar
    python scripts/dashboard_user_admin.py desativar --email dan@acme.test

Le `TENANTS_DATABASE_URL` do env. Apenas para uso administrativo —
provisionamento normal de cliente acontece via API/pipeline futuro.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.clientes_users_repo import obter_repo as obter_users_repo  # noqa: E402
from auth.sessao_service import SessaoService  # noqa: E402
from auth.tenants_repo import obter_repo as obter_tenants_repo  # noqa: E402


def cmd_criar(args):
    url = os.environ["TENANTS_DATABASE_URL"]
    tr = obter_tenants_repo(url)
    ur = obter_users_repo(url)
    svc = SessaoService(ur)

    site = tr.obter_site_por_slug(args.site_slug)
    if site is None:
        if not args.criar_site:
            print(f"erro: site '{args.site_slug}' nao existe. "
                  f"Use --criar-site --site-nome ... --site-dominio ...")
            sys.exit(1)
        if not args.site_nome or not args.site_dominio:
            print("erro: --site-nome e --site-dominio sao obrigatorios com --criar-site")
            sys.exit(1)
        site = tr.criar_site(
            slug=args.site_slug, nome=args.site_nome,
            ambiente=args.site_ambiente, dominios=[args.site_dominio],
        )
        print(f"site criado: {site.id} ({site.slug})")
    else:
        print(f"site existente: {site.id} ({site.slug})")

    if ur.obter_user_por_email(args.email):
        print(f"erro: user com email {args.email} ja existe")
        sys.exit(1)

    user = svc.criar_user(site.id, args.email, papel=args.papel,
                           senha=args.senha if args.senha else None)
    print(f"user criado: {user.id} email={user.email} papel={user.papel}")


def cmd_listar(args):
    url = os.environ["TENANTS_DATABASE_URL"]
    if url.startswith(("postgresql://", "postgres://")):
        import psycopg
        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT u.email, u.papel, u.ativo, s.slug "
                "FROM clientes_users u JOIN sites s ON s.id = u.site_id "
                "ORDER BY u.criado_em"
            )
            rows = cur.fetchall()
    else:
        import sqlite3
        path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else url
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT u.email, u.papel, u.ativo, s.slug "
            "FROM clientes_users u JOIN sites s ON s.id = u.site_id "
            "ORDER BY u.criado_em"
        ).fetchall()

    if not rows:
        print("(nenhum user)")
        return
    for email, papel, ativo, slug in rows:
        print(f"{email:30s}  papel={papel:6s}  ativo={bool(ativo)}  site={slug}")


def cmd_desativar(args):
    url = os.environ["TENANTS_DATABASE_URL"]
    ur = obter_users_repo(url)
    user = ur.obter_user_por_email(args.email)
    if user is None:
        print(f"erro: user '{args.email}' nao existe")
        sys.exit(1)
    ur.desativar_user(user.id)
    print(f"user {args.email} desativado")


def main():
    p = argparse.ArgumentParser(description="Admin CLI do dashboard do cliente")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("criar", help="Cria user (e opcionalmente site)")
    c.add_argument("--site-slug", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--senha", default=None, help="Se omitido, user so loga via magic-link")
    c.add_argument("--papel", default="viewer", choices=["admin", "viewer"])
    c.add_argument("--criar-site", action="store_true",
                    help="Cria o site se nao existir (precisa --site-nome + --site-dominio)")
    c.add_argument("--site-nome", default=None)
    c.add_argument("--site-dominio", default=None)
    c.add_argument("--site-ambiente", default="development",
                    choices=["development", "test", "staging", "production"])
    c.set_defaults(func=cmd_criar)

    l = sub.add_parser("listar", help="Lista users do dashboard")
    l.set_defaults(func=cmd_listar)

    d = sub.add_parser("desativar", help="Desativa user")
    d.add_argument("--email", required=True)
    d.set_defaults(func=cmd_desativar)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
