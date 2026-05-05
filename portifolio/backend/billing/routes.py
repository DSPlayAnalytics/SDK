"""Blueprint Flask com rotas publicas do billing.

Endpoints:
  GET  /billing/planos    — lista os planos disponiveis (free e pro) com quotas e preco.
                            Publico (sem auth) — consumido pelo frontend para renderizar comparacao.
  POST /billing/checkout  — cria sessao Stripe Checkout para upgrade de plano.
                            Requer sessao autenticada (cookie cliente_session com site_id).
                            Retorna {"checkout_url": "https://checkout.stripe.com/..."}.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, jsonify, request, session

from .plano_service import PLANO_DEFAULTS

logger = logging.getLogger(__name__)

billing_routes_bp = Blueprint("billing_routes", __name__, url_prefix="/billing")

# Ordem canonica de exibicao dos planos
_ORDEM_PLANOS = ("free", "pro")

# Mapa de IDs para nomes de exibicao
_NOMES = {
    "free": "Free",
    "pro":  "Pro",
}

# Preco mensal por plano (None = gratuito)
_PRECOS: dict[str, float | None] = {
    "free": None,
    "pro":  99.0,
}

# Planos que podem ser comprados via Checkout (free nao tem preco)
_PLANOS_PAGOS = {"pro"}

_DEFAULT_SUCCESS_URL = (
    "https://dsplayground.com.br/cliente/configuracoes?tab=faturamento&checkout=success"
)
_DEFAULT_CANCEL_URL = (
    "https://dsplayground.com.br/cliente/configuracoes?tab=faturamento&checkout=cancelled"
)


def _criar_stripe_session(
    api_key: str,
    price_id: str,
    site_id: str,
    plano: str,
    success_url: str,
    cancel_url: str,
) -> dict:
    """Chama POST https://api.stripe.com/v1/checkout/sessions via urllib.

    Retorna o objeto JSON da resposta do Stripe.
    Pode lancar urllib.error.HTTPError em caso de erro da API.
    """
    data = urllib.parse.urlencode({
        "payment_method_types[]": "card",
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "metadata[site_id]": site_id,
        "metadata[plano]": plano,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }).encode()
    req = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


@billing_routes_bp.route("/checkout", methods=["POST"])
def criar_checkout():
    """Cria uma sessao Stripe Checkout para upgrade de plano.

    POST /billing/checkout
    Body JSON: {"plano": "pro"}
    Requer: sessao autenticada (site_id em Flask session).

    Retorna:
        200 {"checkout_url": "https://checkout.stripe.com/..."}
        401 nao autenticado
        422 {"erro": "plano_invalido"}   — plano free ou desconhecido
        503 {"erro": "stripe_nao_configurado"}   — env ausente
        502 {"erro": "stripe_erro", "detalhe": str}  — falha na API Stripe
    """
    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        return jsonify({"erro": "stripe_nao_configurado"}), 503

    site_id = session.get("site_id")
    if not site_id:
        return jsonify({"erro": "nao_autenticado"}), 401

    body = request.get_json(silent=True) or {}
    plano = body.get("plano", "")
    if plano == "free":
        return jsonify({"erro": "plano_invalido"}), 422
    if plano not in _PLANOS_PAGOS:
        return jsonify({"erro": "plano_invalido"}), 422

    price_ids_raw = os.environ.get("STRIPE_PRICE_IDS")
    if not price_ids_raw:
        return jsonify({"erro": "stripe_nao_configurado"}), 503

    try:
        price_ids: dict = json.loads(price_ids_raw)
    except (json.JSONDecodeError, ValueError):
        logger.error("evento=billing_price_ids_invalido raw=%r", price_ids_raw)
        return jsonify({"erro": "stripe_nao_configurado"}), 503

    price_id = price_ids.get(plano)
    if not price_id:
        logger.error("evento=billing_price_id_ausente plano=%s", plano)
        return jsonify({"erro": "stripe_nao_configurado"}), 503

    success_url = os.environ.get("BILLING_SUCCESS_URL", _DEFAULT_SUCCESS_URL)
    cancel_url = os.environ.get("BILLING_CANCEL_URL", _DEFAULT_CANCEL_URL)

    try:
        stripe_session = _criar_stripe_session(
            api_key, price_id, site_id, plano, success_url, cancel_url
        )
    except urllib.error.HTTPError as exc:
        logger.warning(
            "evento=billing_stripe_erro site_id=%s plano=%s status=%d",
            site_id, plano, exc.code,
        )
        return jsonify({"erro": "stripe_erro", "detalhe": str(exc)}), 502
    except Exception as exc:
        logger.error(
            "evento=billing_stripe_excecao site_id=%s plano=%s erro=%r",
            site_id, plano, exc,
        )
        return jsonify({"erro": "stripe_erro", "detalhe": str(exc)}), 502

    checkout_url = stripe_session.get("url")
    return jsonify({"checkout_url": checkout_url}), 200


@billing_routes_bp.route("/planos", methods=["GET"])
def listar_planos():
    """Lista os planos disponíveis com suas quotas.

    GET /billing/planos
    Publico — sem autenticacao.

    Retorna:
        {
          "planos": [
            {
              "id": "free",
              "nome": "Free",
              "eventos_por_dia": 10000,
              "eventos_por_minuto": 600,
              "retencao_dias": 7,
              "preco_mensal": null
            },
            ...
          ]
        }
    """
    planos = []
    for plano_id in _ORDEM_PLANOS:
        defaults = PLANO_DEFAULTS[plano_id]
        planos.append({
            "id": plano_id,
            "nome": _NOMES[plano_id],
            "eventos_por_dia": defaults["eventos_por_dia"],
            "eventos_por_minuto": defaults["eventos_por_minuto"],
            "retencao_dias": defaults["retencao_dias"],
            "preco_mensal": _PRECOS[plano_id],
        })
    return jsonify({"planos": planos}), 200
