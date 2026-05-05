"""Blueprint Flask para receber webhooks do Stripe.

Variaveis de ambiente necessarias:
  STRIPE_WEBHOOK_SECRET  — segredo do endpoint Stripe (whsec_...) usado para
                           verificar a assinatura HMAC-SHA256 do header
                           Stripe-Signature. Obrigatorio para o endpoint funcionar.
  STRIPE_API_KEY         — chave de API do Stripe (sk_live_... / sk_test_...).
                           Nao usada diretamente por este modulo (sem SDK Stripe),
                           mas deve estar presente para futuras chamadas a API REST
                           do Stripe (ex.: cancelamentos, reembolsos).

Nota: nao usa o pacote `stripe`. Verificacao feita manualmente com hmac+hashlib,
replicando exatamente o algoritmo descrito em:
  https://docs.stripe.com/webhooks/signature-verification
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

from flask import Blueprint, jsonify, request

from auth.tenants_repo import obter_repo as obter_tenants_repo
from billing.plano_service import aplicar_plano

logger = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")


def _verificar_assinatura(payload: bytes, header: str, secret: str) -> bool:
    """Verifica a assinatura Stripe-Signature (HMAC-SHA256).

    Formato do header: t=<timestamp>,v1=<hex_digest>[,v1=<hex_digest>...]
    Algoritmo:
      signed_payload = f"{timestamp}.{payload_raw}"
      expected = HMAC-SHA256(secret, signed_payload)
    Tolera ate 300s de diferenca entre timestamp do header e now().
    """
    partes = {k: v for k, v in (p.split("=", 1) for p in header.split(",") if "=" in p)}
    ts_str = partes.get("t")
    v1 = partes.get("v1")
    if not ts_str or not v1:
        return False

    try:
        ts = int(ts_str)
    except ValueError:
        return False

    # Tolerancia de 5 minutos (300s) — padrao Stripe
    if abs(time.time() - ts) > 300:
        return False

    signed_payload = f"{ts_str}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


@billing_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Recebe e processa eventos do Stripe.

    POST /billing/stripe/webhook
    """
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        return jsonify({"error": "billing_not_configured"}), 501

    sig_header = request.headers.get("Stripe-Signature", "")
    payload = request.get_data()

    if not _verificar_assinatura(payload, sig_header, secret):
        return jsonify({"error": "invalid_signature"}), 400

    try:
        import json
        event = json.loads(payload)
    except Exception:
        return jsonify({"error": "invalid_payload"}), 400

    event_type = event.get("type", "")
    event_id = event.get("id")

    # Idempotencia: Stripe re-entrega webhooks em retries (timeout, 5xx).
    # Sem o gate abaixo, aplicar_plano() rodava N vezes pro mesmo evento e podia
    # bagunçar transicoes (ex: created+updated chegando fora de ordem).
    # marcar_evento_stripe_processado retorna False quando ja processamos antes.
    if event_id:
        try:
            repo = obter_tenants_repo()
            if not repo.marcar_evento_stripe_processado(event_id):
                logger.info("billing webhook duplicado event_id=%s tipo=%s — ignorando", event_id, event_type)
                return jsonify({"received": True, "duplicate": True}), 200
        except Exception as exc:
            # Erro pra marcar idempotencia nao pode derrubar o webhook (Stripe
            # retentaria mesmo assim). Loga e segue — pior caso, processamos 2x.
            logger.error("billing webhook idempotencia falhou event_id=%s: %s", event_id, exc)

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        subscription = event.get("data", {}).get("object", {})
        metadata = subscription.get("metadata", {})
        site_id = metadata.get("site_id")
        novo_plano = metadata.get("plano")

        if not site_id:
            return jsonify({"error": "missing_metadata"}), 422

        if not novo_plano:
            return jsonify({"error": "missing_metadata"}), 422

        try:
            repo = obter_tenants_repo()
            aplicar_plano(site_id, novo_plano, repo)
        except ValueError as exc:
            logger.warning("billing webhook plano invalido site=%s plano=%s: %s", site_id, novo_plano, exc)
            # Plano invalido no metadata — nao crashar o webhook, logar e ignorar
            return jsonify({"received": True}), 200
        except Exception as exc:
            logger.error("billing webhook erro site=%s plano=%s: %s", site_id, novo_plano, exc)
            return jsonify({"error": "internal"}), 500

        return jsonify({"received": True}), 200

    elif event_type == "customer.subscription.deleted":
        subscription = event.get("data", {}).get("object", {})
        metadata = subscription.get("metadata", {})
        site_id = metadata.get("site_id")

        if not site_id:
            return jsonify({"error": "missing_metadata"}), 422

        try:
            repo = obter_tenants_repo()
            aplicar_plano(site_id, "free", repo)
        except Exception as exc:
            logger.error("billing webhook delete erro site=%s: %s", site_id, exc)
            return jsonify({"error": "internal"}), 500

        return jsonify({"received": True}), 200

    # Evento desconhecido — ignora silenciosamente
    return jsonify({"received": True}), 200
