"""Logica de upgrade/downgrade de plano para tenants.

PLANO_DEFAULTS e a fonte unica de verdade sobre limites por plano.
Valores identicos a scripts.provisionar_cliente.PLANO_DEFAULTS —
se alterar aqui, altere la tambem (e vice-versa).
Ver: ark/docs/dashboard-cliente.md sec. 18.
"""

from __future__ import annotations

# Defaults por plano. Manter sincronizado com scripts/provisionar_cliente.py.
PLANO_DEFAULTS: dict = {
    "free": {"retencao_dias":  7, "eventos_por_dia":    100_000, "eventos_por_minuto":    600},
    "pro":  {"retencao_dias": 90, "eventos_por_dia":  5_000_000, "eventos_por_minuto": 10_000},
}


def aplicar_plano(site_id: str, novo_plano: str, tenants_repo) -> bool:
    """Atualiza sites.plano + quotas do site para o novo_plano.

    Retorna True se o plano foi alterado, False se ja era igual (idempotente).

    Raises:
        ValueError: se novo_plano nao estiver em PLANO_DEFAULTS.
        LookupError: se o site nao existir no repo.
    """
    if novo_plano not in PLANO_DEFAULTS:
        raise ValueError(
            f"plano invalido: '{novo_plano}'. "
            f"Valores aceitos: {list(PLANO_DEFAULTS.keys())}"
        )

    site = tenants_repo.obter_site(site_id)
    if site is None:
        raise LookupError(f"site nao encontrado: '{site_id}'")

    if site.plano == novo_plano:
        return False

    defaults = PLANO_DEFAULTS[novo_plano]
    tenants_repo.atualizar_quota(
        site_id,
        eventos_por_dia=defaults["eventos_por_dia"],
        eventos_por_minuto=defaults["eventos_por_minuto"],
        retencao_dias=defaults["retencao_dias"],
    )
    tenants_repo.atualizar_plano(site_id, novo_plano)
    return True
