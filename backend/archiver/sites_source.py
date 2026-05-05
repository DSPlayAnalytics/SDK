"""Adapter que combina TenantsRepo.listar_sites + obter_quota em SiteArquivavel.

Mantido separado pra:
- Permitir injetar `tenants_repo` mockado em testes
- Permitir trocar implementacao (ex: filtrar sites pelo `status='ativo'`)
"""
from typing import List

from .scheduler import SiteArquivavel


def listar_sites_arquivaveis(tenants_repo) -> List[SiteArquivavel]:
    sites_arquivaveis: List[SiteArquivavel] = []
    for site in tenants_repo.listar_sites():
        if site.status != 'ativo':
            continue
        if not site.slug:
            continue
        quota = tenants_repo.obter_quota(site.id)
        retencao = quota.retencao_dias if quota else 30
        sites_arquivaveis.append(SiteArquivavel(
            slug=site.slug,
            plano=site.plano,
            retencao_dias=retencao,
        ))
    return sites_arquivaveis
