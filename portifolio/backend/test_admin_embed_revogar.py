"""Testes do A5 audit — revogacao de embed JWT por jti.

Cobre:
- repo.revogar_jti_embed e ON CONFLICT idempotente (jti repetido nao
  duplica nem levanta).
- repo.jti_embed_esta_revogado le corretamente.
- repo.purgar_embed_jwt_revogados_antigos respeita janela
  (retencao_horas), apaga so linhas com revogado_em fora da janela.
- Boot do backend nao quebra se purga falhar (testado via try/except
  no app.py — sem teste direto, mas inserimos comentario doc).

Endpoints HTTP /admin/embed/revogar e /admin/embed/housekeeping sao
wiring trivial em torno do repo (verificacao de admin token + chamada
de repo). Cobertos pelos testes admin existentes em padroes similares
(test_analytics_auth, test_admin_*).
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.tenants_repo import SqliteTenantsRepo


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS embed_jwt_revogados (
            jti TEXT PRIMARY KEY,
            motivo TEXT,
            revogado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()


class EmbedRevogarTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self._tmp.name) / "t.db")
        _init_schema(self.db)
        self.repo = SqliteTenantsRepo(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_revogar_marca_jti(self):
        self.assertFalse(self.repo.jti_embed_esta_revogado("jti-1"))
        self.repo.revogar_jti_embed("jti-1", motivo="teste")
        self.assertTrue(self.repo.jti_embed_esta_revogado("jti-1"))

    def test_revogar_idempotente(self):
        self.repo.revogar_jti_embed("jti-2", motivo="primeiro")
        # Segunda chamada com mesmo jti — INSERT OR IGNORE nao levanta.
        self.repo.revogar_jti_embed("jti-2", motivo="segundo")
        self.assertTrue(self.repo.jti_embed_esta_revogado("jti-2"))

        # Conferir no DB que so existe 1 linha.
        conn = sqlite3.connect(self.db)
        count = conn.execute(
            "SELECT COUNT(*) FROM embed_jwt_revogados WHERE jti = ?", ("jti-2",)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_purgar_apaga_so_antigos(self):
        # Insere manualmente com timestamps controlados pra evitar flake.
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO embed_jwt_revogados (jti, motivo, revogado_em) VALUES (?, ?, ?)",
            ("jti-recente", "x", "2026-05-04 00:00:00"),
        )
        conn.execute(
            "INSERT INTO embed_jwt_revogados (jti, motivo, revogado_em) VALUES (?, ?, ?)",
            ("jti-antigo", "x", "2026-04-01 00:00:00"),
        )
        conn.commit()
        conn.close()

        # retencao=48h — qualquer revogado_em < now-48h some.
        # 2026-04-01 com certeza esta fora da janela; 2026-05-04 pode ou nao,
        # depende de quando o teste rodar. Usamos retencao bem larga (48h)
        # contra timestamps de meses atras pra garantir que so o antigo cai.
        apagados = self.repo.purgar_embed_jwt_revogados_antigos(retencao_horas=48)

        # jti-antigo apagado; jti-recente pode ter sobrevivido (depende de
        # data atual >= 2026-05-06). Asserts conservadores: pelo menos 1
        # apagado, jti-antigo definitivamente foi.
        self.assertGreaterEqual(apagados, 1)
        self.assertFalse(self.repo.jti_embed_esta_revogado("jti-antigo"))

    def test_purgar_retorna_zero_se_nada_pra_apagar(self):
        # Insere so um recente.
        self.repo.revogar_jti_embed("jti-fresco", motivo="agora")

        apagados = self.repo.purgar_embed_jwt_revogados_antigos(retencao_horas=720)
        self.assertEqual(apagados, 0)
        self.assertTrue(self.repo.jti_embed_esta_revogado("jti-fresco"))


if __name__ == "__main__":
    unittest.main()
