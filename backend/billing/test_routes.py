"""TDD para billing.routes — GET /billing/planos.

Testa:
  1. Status 200
  2. Retorna os 2 planos (free, pro) na ordem com as chaves certas
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from flask import Flask

from billing.plano_service import PLANO_DEFAULTS
from billing.routes import billing_routes_bp


def _criar_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(billing_routes_bp)
    app.testing = True
    return app


class ListarPlanosTests(unittest.TestCase):
    def setUp(self):
        self.client = _criar_app().test_client()

    # 1. Status 200
    def test_retorna_status_200(self):
        r = self.client.get("/billing/planos")
        self.assertEqual(r.status_code, 200)

    # 2. Retorna os 2 planos atuais (free, pro) com chaves corretas
    def test_retorna_dois_planos_na_ordem_com_chaves_corretas(self):
        r = self.client.get("/billing/planos")
        body = r.get_json()

        self.assertIn("planos", body)
        planos = body["planos"]
        self.assertEqual(len(planos), 2)

        # Ordem canonica: gratuito primeiro, depois pago
        self.assertEqual([p["id"] for p in planos], ["free", "pro"])

        # Chaves obrigatorias em todos os planos
        chaves_esperadas = {"id", "nome", "eventos_por_dia", "eventos_por_minuto",
                            "retencao_dias", "preco_mensal"}
        for p in planos:
            self.assertEqual(set(p.keys()), chaves_esperadas, msg=f"plano {p['id']} faltando chaves")

        # Valores spot-check do free — sincronizados com PLANO_DEFAULTS
        free = planos[0]
        self.assertEqual(free["id"], "free")
        self.assertEqual(free["nome"], "Free")
        self.assertEqual(free["eventos_por_dia"], PLANO_DEFAULTS["free"]["eventos_por_dia"])
        self.assertEqual(free["eventos_por_minuto"], PLANO_DEFAULTS["free"]["eventos_por_minuto"])
        self.assertEqual(free["retencao_dias"], PLANO_DEFAULTS["free"]["retencao_dias"])
        self.assertIsNone(free["preco_mensal"])  # gratuito

        # Pro: pago, valores do PLANO_DEFAULTS
        pro = planos[1]
        self.assertEqual(pro["id"], "pro")
        self.assertEqual(pro["nome"], "Pro")
        self.assertEqual(pro["eventos_por_dia"], PLANO_DEFAULTS["pro"]["eventos_por_dia"])
        self.assertEqual(pro["eventos_por_minuto"], PLANO_DEFAULTS["pro"]["eventos_por_minuto"])
        self.assertEqual(pro["retencao_dias"], PLANO_DEFAULTS["pro"]["retencao_dias"])
        self.assertIsNotNone(pro["preco_mensal"])  # pago
        self.assertGreater(pro["preco_mensal"], 0)


if __name__ == "__main__":
    unittest.main()
