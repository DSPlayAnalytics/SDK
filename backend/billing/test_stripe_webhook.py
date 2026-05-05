"""Testes TDD para billing.stripe_webhook (POST /billing/stripe/webhook).

Usa SqliteTenantsRepo e app.test_client(). Nao depende do Stripe SDK.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth import tenants_repo as tenants_repo_mod
from auth.tenants_repo import SqliteTenantsRepo
from billing.stripe_webhook import billing_bp
from flask import Flask


def _assinar(payload: bytes, secret: str) -> str:
    """Replica exatamente o algoritmo do Stripe para gerar Stripe-Signature."""
    ts = int(time.time())
    signed = hmac.new(
        secret.encode(),
        f"{ts}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={signed}"


def _criar_app(repo: SqliteTenantsRepo) -> Flask:
    app = Flask(__name__)
    app.testing = True
    tenants_repo_mod._repo_instance = repo
    app.register_blueprint(billing_bp)
    return app


def _payload_subscription(site_id: str, plano: str, event_type: str) -> bytes:
    event = {
        "type": event_type,
        "data": {
            "object": {
                "id": "sub_test",
                "metadata": {
                    "site_id": site_id,
                    "plano": plano,
                },
            }
        },
    }
    return json.dumps(event).encode()


def _payload_deleted(site_id: str) -> bytes:
    event = {
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test",
                "metadata": {
                    "site_id": site_id,
                },
            }
        },
    }
    return json.dumps(event).encode()


class StripeWebhookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = SqliteTenantsRepo(str(Path(self._tmp.name) / "tenants.db"))
        self.app = _criar_app(self.repo)
        self.client = self.app.test_client()
        self.secret = "whsec_test_secret_123"
        # Cria um site para os testes que precisam de site real
        self.site = self.repo.criar_site(
            slug="acme", nome="Acme Corp", ambiente="test",
            dominios=["https://acme.example.com"], plano="free",
        )

    def tearDown(self):
        tenants_repo_mod._repo_instance = None
        self._tmp.cleanup()

    def _post(self, payload: bytes, sig: str) -> object:
        return self.client.post(
            "/billing/stripe/webhook",
            data=payload,
            content_type="application/json",
            headers={"Stripe-Signature": sig},
        )

    # 1. Sem STRIPE_WEBHOOK_SECRET -> 501
    def test_sem_secret_retorna_501(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
            resp = self.client.post(
                "/billing/stripe/webhook",
                data=b"{}",
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 501)
        self.assertEqual(resp.get_json()["error"], "billing_not_configured")

    # 2. Assinatura invalida -> 400
    def test_assinatura_invalida_retorna_400(self):
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": self.secret}):
            resp = self._post(b'{"type":"customer.subscription.created"}', "t=123,v1=invalido")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "invalid_signature")

    # 3. subscription.created com metadata valido -> 200, plano atualizado
    def test_subscription_created_atualiza_plano(self):
        payload = _payload_subscription(self.site.id, "pro", "customer.subscription.created")
        sig = _assinar(payload, self.secret)
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": self.secret}):
            resp = self._post(payload, sig)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["received"])
        site_atualizado = self.repo.obter_site(self.site.id)
        self.assertEqual(site_atualizado.plano, "pro")

    # 4. subscription.deleted -> 200, downgrade para free
    def test_subscription_deleted_faz_downgrade_free(self):
        # Primeiro coloca no plano pro
        from billing.plano_service import aplicar_plano
        aplicar_plano(self.site.id, "pro", self.repo)

        payload = _payload_deleted(self.site.id)
        sig = _assinar(payload, self.secret)
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": self.secret}):
            resp = self._post(payload, sig)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["received"])
        site_atualizado = self.repo.obter_site(self.site.id)
        self.assertEqual(site_atualizado.plano, "free")

    # 5. Evento desconhecido -> 200 {"received": true}
    def test_evento_desconhecido_retorna_200(self):
        payload = json.dumps({"type": "invoice.created", "data": {"object": {}}}).encode()
        sig = _assinar(payload, self.secret)
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": self.secret}):
            resp = self._post(payload, sig)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["received"])

    # 6. metadata.site_id ausente -> 422
    def test_sem_site_id_retorna_422(self):
        event = {
            "type": "customer.subscription.created",
            "data": {"object": {"metadata": {"plano": "pequeno"}}},
        }
        payload = json.dumps(event).encode()
        sig = _assinar(payload, self.secret)
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": self.secret}):
            resp = self._post(payload, sig)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["error"], "missing_metadata")

    # 7. metadata.plano invalido -> 200 (log + ignora gracefully)
    def test_plano_invalido_nao_crasha_webhook(self):
        payload = _payload_subscription(self.site.id, "ultra_premium_x", "customer.subscription.created")
        sig = _assinar(payload, self.secret)
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": self.secret}):
            resp = self._post(payload, sig)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["received"])
        # Plano nao deve ter mudado
        site_atualizado = self.repo.obter_site(self.site.id)
        self.assertEqual(site_atualizado.plano, "free")


if __name__ == "__main__":
    unittest.main()
