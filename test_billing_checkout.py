"""TDD para POST /billing/checkout — cria sessao Stripe Checkout.

Testes escritos ANTES da implementacao (TDD/XP).

Cenarios:
  1. 503 quando STRIPE_API_KEY nao configurada (stub mode)
  2. 401 quando nao ha sessao autenticada
  3. 422 quando plano e "free" (nao pode pagar pelo free)
  4. 422 quando plano e desconhecido
  5. 503 quando STRIPE_PRICE_IDS nao configurado
  6. 200 com checkout_url retornado (mock _criar_stripe_session)
  7. 502 quando _criar_stripe_session lanca urllib.error.HTTPError
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from flask import Flask
from billing.routes import billing_routes_bp


def _criar_app() -> Flask:
    app = Flask(__name__)
    app.testing = True
    app.secret_key = "test-secret-key"
    app.register_blueprint(billing_routes_bp)
    return app


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.app = _criar_app()
        self.client = self.app.test_client()

    def _post(self, body: dict, *, env: dict | None = None, session_data: dict | None = None):
        env_vars = env or {}
        # Garante que STRIPE_API_KEY nao esta no ambiente por default
        clean_env = {k: v for k, v in os.environ.items() if k != "STRIPE_API_KEY"}
        clean_env.update(env_vars)

        with patch.dict(os.environ, clean_env, clear=True):
            with self.client.session_transaction() as sess:
                if session_data:
                    sess.update(session_data)
            return self.client.post(
                "/billing/checkout",
                data=json.dumps(body),
                content_type="application/json",
            )

    # 1. Sem STRIPE_API_KEY -> 503 stripe_nao_configurado
    def test_503_stripe_nao_configurado(self):
        with patch.dict(os.environ, {}, clear=True):
            # Garante que STRIPE_API_KEY nao esta no ambiente
            env = {k: v for k, v in os.environ.items() if k != "STRIPE_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                with self.client.session_transaction() as sess:
                    sess["site_id"] = "site-abc"
                resp = self.client.post(
                    "/billing/checkout",
                    data=json.dumps({"plano": "pro"}),
                    content_type="application/json",
                )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["erro"], "stripe_nao_configurado")

    # 2. Sem sessao autenticada -> 401
    def test_401_nao_autenticado(self):
        with patch.dict(os.environ, {"STRIPE_API_KEY": "sk_test_xxx"}, clear=False):
            resp = self.client.post(
                "/billing/checkout",
                data=json.dumps({"plano": "pro"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 401)

    # 3. Plano "free" -> 422 plano_invalido
    def test_422_plano_invalido_free(self):
        with patch.dict(os.environ, {"STRIPE_API_KEY": "sk_test_xxx"}, clear=False):
            with self.client.session_transaction() as sess:
                sess["site_id"] = "site-abc"
            resp = self.client.post(
                "/billing/checkout",
                data=json.dumps({"plano": "free"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["erro"], "plano_invalido")

    # 4. Plano desconhecido -> 422 plano_invalido
    def test_422_plano_desconhecido(self):
        with patch.dict(os.environ, {"STRIPE_API_KEY": "sk_test_xxx"}, clear=False):
            with self.client.session_transaction() as sess:
                sess["site_id"] = "site-abc"
            resp = self.client.post(
                "/billing/checkout",
                data=json.dumps({"plano": "ultra"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["erro"], "plano_invalido")

    # 5. Sem STRIPE_PRICE_IDS -> 503
    def test_503_price_ids_nao_configurado(self):
        env = {k: v for k, v in os.environ.items() if k not in ("STRIPE_API_KEY", "STRIPE_PRICE_IDS")}
        env["STRIPE_API_KEY"] = "sk_test_xxx"
        with patch.dict(os.environ, env, clear=True):
            with self.client.session_transaction() as sess:
                sess["site_id"] = "site-abc"
            resp = self.client.post(
                "/billing/checkout",
                data=json.dumps({"plano": "pro"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["erro"], "stripe_nao_configurado")

    # 6. Sucesso -> 200 com checkout_url
    def test_200_checkout_url_retornado(self):
        price_ids = json.dumps({"pro": "price_pro"})
        env = {k: v for k, v in os.environ.items()}
        env["STRIPE_API_KEY"] = "sk_test_xxx"
        env["STRIPE_PRICE_IDS"] = price_ids

        mock_session = {"url": "https://checkout.stripe.com/abc"}

        with patch.dict(os.environ, env, clear=True):
            with patch("billing.routes._criar_stripe_session", return_value=mock_session) as mock_fn:
                with self.client.session_transaction() as sess:
                    sess["site_id"] = "site-abc"
                resp = self.client.post(
                    "/billing/checkout",
                    data=json.dumps({"plano": "pro"}),
                    content_type="application/json",
                )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("checkout_url", body)
        self.assertEqual(body["checkout_url"], "https://checkout.stripe.com/abc")
        # Verifica que foi chamado com os args corretos
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args
        self.assertEqual(call_kwargs[0][0], "sk_test_xxx")   # api_key
        self.assertEqual(call_kwargs[0][1], "price_pro")     # price_id
        self.assertEqual(call_kwargs[0][2], "site-abc")       # site_id
        self.assertEqual(call_kwargs[0][3], "pro")            # plano

    # 7. _criar_stripe_session lanca HTTPError -> 502
    def test_502_stripe_erro(self):
        price_ids = json.dumps({"pro": "price_pro"})
        env = {k: v for k, v in os.environ.items()}
        env["STRIPE_API_KEY"] = "sk_test_xxx"
        env["STRIPE_PRICE_IDS"] = price_ids

        http_error = urllib.error.HTTPError(
            url="https://api.stripe.com/v1/checkout/sessions",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

        with patch.dict(os.environ, env, clear=True):
            with patch("billing.routes._criar_stripe_session", side_effect=http_error):
                with self.client.session_transaction() as sess:
                    sess["site_id"] = "site-abc"
                resp = self.client.post(
                    "/billing/checkout",
                    data=json.dumps({"plano": "pro"}),
                    content_type="application/json",
                )

        self.assertEqual(resp.status_code, 502)
        body = resp.get_json()
        self.assertEqual(body["erro"], "stripe_erro")
        self.assertIn("detalhe", body)


if __name__ == "__main__":
    unittest.main()
