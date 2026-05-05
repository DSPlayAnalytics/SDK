"""Testes para TenantsRepo (SqliteTenantsRepo em memória).

Cobre consumo_em_dia e consumo_hoje em SqliteTenantsRepo.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.tenants_repo import SqliteTenantsRepo


class ConsumoEmDiaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(self._tmp.name) / "tenants.db")
        self.repo = SqliteTenantsRepo(db_path)
        self.site = self.repo.criar_site("acme", "ACME", "production", [])

    def tearDown(self):
        self._tmp.cleanup()

    def test_consumo_em_dia_retorna_zero_sem_registros(self):
        dia = date(2026, 5, 1)
        resultado = self.repo.consumo_em_dia(self.site.id, dia)
        self.assertEqual(resultado, 0)

    def test_consumo_em_dia_retorna_valor_correto_apos_incrementar(self):
        # incrementar_consumo usa hoje — injetamos diretamente via SQL para
        # testar um dia arbitrário
        dia = date(2026, 4, 30)
        import sqlite3
        db_path = self.repo._db_path
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.execute(
            "INSERT INTO consumo_diario (site_id, dia, eventos) VALUES (?, ?, ?)",
            (self.site.id, dia.isoformat(), 42),
        )
        conn.close()

        resultado = self.repo.consumo_em_dia(self.site.id, dia)
        self.assertEqual(resultado, 42)

    def test_consumo_em_dia_nao_confunde_dias_distintos(self):
        import sqlite3
        db_path = self.repo._db_path
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.execute(
            "INSERT INTO consumo_diario (site_id, dia, eventos) VALUES (?, ?, ?)",
            (self.site.id, "2026-05-01", 10),
        )
        conn.execute(
            "INSERT INTO consumo_diario (site_id, dia, eventos) VALUES (?, ?, ?)",
            (self.site.id, "2026-05-02", 99),
        )
        conn.close()

        self.assertEqual(self.repo.consumo_em_dia(self.site.id, date(2026, 5, 1)), 10)
        self.assertEqual(self.repo.consumo_em_dia(self.site.id, date(2026, 5, 2)), 99)

    def test_consumo_em_dia_nao_confunde_sites_distintos(self):
        site2 = self.repo.criar_site("beta", "Beta", "production", [])
        import sqlite3
        db_path = self.repo._db_path
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.execute(
            "INSERT INTO consumo_diario (site_id, dia, eventos) VALUES (?, ?, ?)",
            (self.site.id, "2026-05-01", 7),
        )
        conn.execute(
            "INSERT INTO consumo_diario (site_id, dia, eventos) VALUES (?, ?, ?)",
            (site2.id, "2026-05-01", 13),
        )
        conn.close()

        self.assertEqual(self.repo.consumo_em_dia(self.site.id, date(2026, 5, 1)), 7)
        self.assertEqual(self.repo.consumo_em_dia(site2.id, date(2026, 5, 1)), 13)

    def test_consumo_hoje_usa_data_de_hoje(self):
        # incrementar_consumo grava em "hoje" — consumo_hoje deve retornar esse valor
        self.repo.incrementar_consumo(self.site.id, 5)
        resultado = self.repo.consumo_hoje(self.site.id)
        self.assertEqual(resultado, 5)

    def test_consumo_hoje_delega_para_consumo_em_dia(self):
        """consumo_hoje(x) == consumo_em_dia(x, date.today())"""
        self.repo.incrementar_consumo(self.site.id, 3)
        hoje = datetime.now(timezone.utc).date()
        self.assertEqual(
            self.repo.consumo_hoje(self.site.id),
            self.repo.consumo_em_dia(self.site.id, hoje),
        )


if __name__ == "__main__":
    unittest.main()
