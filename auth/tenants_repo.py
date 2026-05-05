"""Repositorio de tenants, publishable_keys, quotas e log de emissoes.

Duas implementacoes com interface unica:

  - `PostgresTenantsRepo` — producao, psycopg v3 com pool de conexoes.
  - `SqliteTenantsRepo` — testes e dev local sem container adicional.

Escolha via `criar_tenants_repo(url)`:
  - `postgresql://user:pass@host:5432/db`  -> Postgres
  - `sqlite:///path/to/file.db`            -> SQLite
  - path absoluto (`/x/y.db`)              -> SQLite (compat com config antigo)
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional, Protocol


SCHEMA_SQLITE_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_POSTGRES_PATH = Path(__file__).resolve().parent / "schema_postgres.sql"


@dataclass(frozen=True)
class Site:
    id: str
    slug: str
    nome: str
    ambiente: str
    plano: str
    status: str
    bucket_name: Optional[str] = None


@dataclass(frozen=True)
class PublishableKey:
    key_id: str
    site_id: str
    valor: str
    nome: Optional[str]
    revogada: bool


@dataclass(frozen=True)
class Quota:
    site_id: str
    eventos_por_minuto: int
    eventos_por_dia: int
    emissoes_jwt_por_minuto: int
    retencao_dias: int


# ---------- interface comum ----------

class TenantsRepo(Protocol):
    """Interface que ambas as implementacoes seguem."""

    # sites
    def criar_site(self, slug: str, nome: str, ambiente: str,
                   dominios: Iterable[str], plano: str = "free",
                   bucket_name: Optional[str] = None) -> Site: ...
    def obter_site(self, site_id: str) -> Optional[Site]: ...
    def obter_site_por_slug(self, slug: str) -> Optional[Site]: ...
    def obter_site_por_bucket(self, bucket_name: str) -> Optional[Site]: ...
    def listar_sites(self) -> list[Site]: ...
    def atualizar_status_site(self, site_id: str, status: str) -> None: ...
    def atualizar_plano(self, site_id: str, plano: str) -> None: ...
    def definir_bucket_name(self, site_id: str, bucket_name: str) -> None: ...

    # dominios
    def listar_dominios(self, site_id: str) -> list[str]: ...
    def adicionar_dominio(self, site_id: str, dominio: str) -> None: ...
    def remover_dominio(self, site_id: str, dominio: str) -> None: ...
    def origin_permitido(self, site_id: str, origin: str) -> bool: ...
    def dominio_existe(self, dominio: str) -> bool: ...

    # publishable
    def criar_publishable_key(self, site_id: str, ambiente: str,
                              nome: Optional[str] = None) -> tuple[PublishableKey, str]: ...
    def obter_publishable_por_valor(self, valor: str) -> Optional[PublishableKey]: ...
    def listar_publishable_keys(self, site_id: str) -> list[PublishableKey]: ...
    def revogar_publishable_key(self, key_id: str) -> None: ...

    # quotas
    def obter_quota(self, site_id: str) -> Optional[Quota]: ...
    def atualizar_quota(self, site_id: str, *,
                        eventos_por_minuto: Optional[int] = None,
                        eventos_por_dia: Optional[int] = None,
                        emissoes_jwt_por_minuto: Optional[int] = None,
                        retencao_dias: Optional[int] = None) -> None: ...

    # consumo
    def consumo_hoje(self, site_id: str) -> int: ...
    def consumo_em_dia(self, site_id: str, dia: date) -> int: ...
    def incrementar_consumo(self, site_id: str, eventos: int = 1) -> None: ...

    # emissoes
    def registrar_emissao(self, *, site_id: str, publishable_id: str, jti: str,
                          origin: Optional[str], ip: Optional[str]) -> None: ...
    def contar_emissoes_recentes(self, publishable_id: str,
                                 janela_segundos: int = 60) -> int: ...
    def limpar_emissoes_antigas(self, dias: int = 7) -> int: ...

    # idempotencia stripe
    def marcar_evento_stripe_processado(self, event_id: str) -> bool: ...
    """Tenta marcar `event_id` como processado. True = inseriu (primeira vez),
    False = ja existia (retry duplicado, descartar)."""

    # revogacao embed jwt
    def jti_embed_esta_revogado(self, jti: str) -> bool: ...
    def revogar_jti_embed(self, jti: str, *, motivo: Optional[str] = None) -> None: ...
    def purgar_embed_jwt_revogados_antigos(self, retencao_horas: int = 48) -> int: ...
    """Apaga linhas de embed_jwt_revogados com revogado_em < now - retencao_horas.
    Retorna quantidade apagada. Chamado no boot do backend (best-effort) e em
    POST /admin/embed/housekeeping. Default 48h cobre TTL_MAX do JWT embed
    (24h hoje) com folga."""


# ======================================================================
#                            SQLite
# ======================================================================


class SqliteTenantsRepo:
    """Implementacao SQLite (testes e dev local sem container adicional)."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        schema = SCHEMA_SQLITE_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)
            self._migrar_schema(conn)

    @staticmethod
    def _migrar_schema(conn: sqlite3.Connection) -> None:
        """Migra DBs criados antes do bucket-per-cliente.

        SQLite nao suporta `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, entao
        verificamos via `PRAGMA table_info` e adicionamos quando faltar.
        """
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}
        if "bucket_name" not in cols:
            conn.execute("ALTER TABLE sites ADD COLUMN bucket_name TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sites_bucket_name "
                "ON sites(bucket_name) WHERE bucket_name IS NOT NULL"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, isolation_level=None, timeout=10.0)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # sites
    def criar_site(self, slug, nome, ambiente, dominios, plano="free", bucket_name=None):
        site_id = str(uuid.uuid4())
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sites (id, slug, nome, ambiente, plano, bucket_name) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (site_id, slug, nome, ambiente, plano, bucket_name),
            )
            for dom in dominios:
                conn.execute(
                    "INSERT INTO site_dominios (site_id, dominio) VALUES (?, ?)",
                    (site_id, dom.rstrip("/")),
                )
            conn.execute("INSERT INTO quotas (site_id) VALUES (?)", (site_id,))
        return Site(id=site_id, slug=slug, nome=nome, ambiente=ambiente, plano=plano,
                    status="ativo", bucket_name=bucket_name)

    def obter_site(self, site_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        return _row_to_site(row) if row else None

    def obter_site_por_slug(self, slug):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sites WHERE slug = ?", (slug,)).fetchone()
        return _row_to_site(row) if row else None

    def obter_site_por_bucket(self, bucket_name):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sites WHERE bucket_name = ?", (bucket_name,)
            ).fetchone()
        return _row_to_site(row) if row else None

    def listar_sites(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sites ORDER BY criado_em").fetchall()
        return [_row_to_site(r) for r in rows]

    def atualizar_status_site(self, site_id, status):
        if status not in ("ativo", "suspenso", "bloqueado"):
            raise ValueError(f"status invalido: {status}")
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sites SET status = ?, atualizado_em = datetime('now') WHERE id = ?",
                (status, site_id),
            )

    def atualizar_plano(self, site_id, plano):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sites SET plano = ?, atualizado_em = datetime('now') WHERE id = ?",
                (plano, site_id),
            )

    def definir_bucket_name(self, site_id, bucket_name):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sites SET bucket_name = ?, atualizado_em = datetime('now') WHERE id = ?",
                (bucket_name, site_id),
            )

    # dominios
    def listar_dominios(self, site_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT dominio FROM site_dominios WHERE site_id = ?", (site_id,)
            ).fetchall()
        return [r["dominio"] for r in rows]

    def adicionar_dominio(self, site_id, dominio):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO site_dominios (site_id, dominio) VALUES (?, ?)",
                (site_id, dominio.rstrip("/")),
            )

    def remover_dominio(self, site_id, dominio):
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM site_dominios WHERE site_id = ? AND dominio = ?",
                (site_id, dominio.rstrip("/")),
            )

    def origin_permitido(self, site_id, origin):
        if not origin:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM site_dominios WHERE site_id = ? AND dominio = ? LIMIT 1",
                (site_id, origin.rstrip("/")),
            ).fetchone()
        return row is not None

    def dominio_existe(self, dominio):
        """Lookup global em site_dominios — qualquer site que tenha esse dominio.

        Usado pelo CORS dinamico (NAO escopa por site_id, ao contrario de
        origin_permitido). Index `idx_site_dominios_dominio` torna O(log n).
        """
        if not dominio:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM site_dominios WHERE dominio = ? LIMIT 1",
                (dominio.rstrip("/"),),
            ).fetchone()
        return row is not None

    # publishable
    def criar_publishable_key(self, site_id, ambiente, nome=None):
        key_id = uuid.uuid4().hex[:12]
        valor = f"pk_{ambiente}_{secrets.token_urlsafe(32)}"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO publishable_keys (key_id, site_id, valor, nome) VALUES (?, ?, ?, ?)",
                (key_id, site_id, valor, nome),
            )
        return PublishableKey(key_id=key_id, site_id=site_id, valor=valor, nome=nome, revogada=False), valor

    def obter_publishable_por_valor(self, valor):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM publishable_keys WHERE valor = ?", (valor,)
            ).fetchone()
        return _row_to_key(row) if row else None

    def listar_publishable_keys(self, site_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM publishable_keys WHERE site_id = ? ORDER BY criado_em",
                (site_id,),
            ).fetchall()
        return [_row_to_key(r) for r in rows]

    def revogar_publishable_key(self, key_id):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE publishable_keys SET revogado_em = datetime('now') WHERE key_id = ?",
                (key_id,),
            )

    # quotas
    def obter_quota(self, site_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM quotas WHERE site_id = ?", (site_id,)).fetchone()
        if not row:
            return None
        return Quota(
            site_id=row["site_id"],
            eventos_por_minuto=row["eventos_por_minuto"],
            eventos_por_dia=row["eventos_por_dia"],
            emissoes_jwt_por_minuto=row["emissoes_jwt_por_minuto"],
            retencao_dias=row["retencao_dias"],
        )

    def atualizar_quota(self, site_id, *, eventos_por_minuto=None, eventos_por_dia=None,
                        emissoes_jwt_por_minuto=None, retencao_dias=None):
        campos = {}
        if eventos_por_minuto is not None: campos["eventos_por_minuto"] = eventos_por_minuto
        if eventos_por_dia is not None: campos["eventos_por_dia"] = eventos_por_dia
        if emissoes_jwt_por_minuto is not None: campos["emissoes_jwt_por_minuto"] = emissoes_jwt_por_minuto
        if retencao_dias is not None: campos["retencao_dias"] = retencao_dias
        if not campos:
            return
        sets = ", ".join(f"{k} = ?" for k in campos)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE quotas SET {sets} WHERE site_id = ?",
                         list(campos.values()) + [site_id])

    # consumo
    def consumo_em_dia(self, site_id: str, dia: date) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT eventos FROM consumo_diario WHERE site_id = ? AND dia = ?",
                (site_id, dia.isoformat()),
            ).fetchone()
        return int(row["eventos"]) if row else 0

    def consumo_hoje(self, site_id):
        return self.consumo_em_dia(site_id, datetime.now(timezone.utc).date())

    def incrementar_consumo(self, site_id, eventos=1):
        dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO consumo_diario (site_id, dia, eventos) VALUES (?, ?, ?)
                ON CONFLICT(site_id, dia) DO UPDATE SET
                    eventos = eventos + excluded.eventos,
                    atualizado_em = datetime('now')
                """,
                (site_id, dia, eventos),
            )

    # emissoes
    def registrar_emissao(self, *, site_id, publishable_id, jti, origin, ip):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO emissoes_jwt (site_id, publishable_id, origin, ip, jti)
                VALUES (?, ?, ?, ?, ?)
                """,
                (site_id, publishable_id, origin, ip, jti),
            )

    def contar_emissoes_recentes(self, publishable_id, janela_segundos=60):
        corte = (datetime.now(timezone.utc) - timedelta(seconds=janela_segundos)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total FROM emissoes_jwt
                WHERE publishable_id = ? AND emitido_em >= ?
                """,
                (publishable_id, corte),
            ).fetchone()
        return int(row["total"]) if row else 0

    def limpar_emissoes_antigas(self, dias=7):
        corte = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM emissoes_jwt WHERE emitido_em < ?", (corte,))
            return cur.rowcount or 0

    # idempotencia stripe
    def marcar_evento_stripe_processado(self, event_id):
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO stripe_eventos_processados (event_id) VALUES (?)",
                (event_id,),
            )
            return (cur.rowcount or 0) > 0

    # revogacao embed jwt
    def jti_embed_esta_revogado(self, jti):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM embed_jwt_revogados WHERE jti = ? LIMIT 1",
                (jti,),
            ).fetchone()
        return row is not None

    def revogar_jti_embed(self, jti, *, motivo=None):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO embed_jwt_revogados (jti, motivo) VALUES (?, ?)",
                (jti, motivo),
            )

    def purgar_embed_jwt_revogados_antigos(self, retencao_horas=48):
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM embed_jwt_revogados "
                "WHERE revogado_em < datetime('now', ? || ' hours')",
                (f'-{int(retencao_horas)}',),
            )
            return cur.rowcount or 0


def _row_to_site(row: sqlite3.Row) -> Site:
    keys = row.keys()
    bucket = row["bucket_name"] if "bucket_name" in keys else None
    return Site(id=row["id"], slug=row["slug"], nome=row["nome"],
                ambiente=row["ambiente"], plano=row["plano"], status=row["status"],
                bucket_name=bucket)


def _row_to_key(row: sqlite3.Row) -> PublishableKey:
    return PublishableKey(key_id=row["key_id"], site_id=row["site_id"],
                          valor=row["valor"], nome=row["nome"],
                          revogada=row["revogado_em"] is not None)


# ======================================================================
#                            Postgres
# ======================================================================


class PostgresTenantsRepo:
    """Implementacao Postgres via psycopg v3 com connection pool.

    Usa `%s` como placeholder (nao `?`). Todas as queries sao parametrizadas;
    interface publica e identica a SqliteTenantsRepo.
    """

    def __init__(self, dsn: str, *, pool_min: int = 1, pool_max: int = 10):
        # Import tardio: psycopg so e obrigatorio em producao.
        from psycopg_pool import ConnectionPool
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=pool_min,
            max_size=pool_max,
            open=True,
            kwargs={"row_factory": _dict_row()},
        )
        schema = SCHEMA_POSTGRES_PATH.read_text(encoding="utf-8")
        with self._conn() as conn:
            with conn.cursor() as cur:
                # Em prod o backend conecta como `portifolio_app` (least-privilege),
                # nao como superuser. Se o DB ja foi configurado pelo Ansible
                # (CREATE TABLE + ALTER OWNER pra portifolio_app), CREATE TABLE
                # IF NOT EXISTS aqui sao no-ops. Mas se algum ALTER TABLE no
                # schema mudar tabela de propriedade alheia, falha com
                # InsufficientPrivilege — comportamento esperado em prod
                # configurada. Logamos warning e seguimos: tabelas existem.
                #
                # Este try/except protege boot pos-DR/clean-room ate o operador
                # rodar `make -f ark/Makefile ansible-apply` (que aplica
                # ALTER OWNER + GRANTs corretos).
                try:
                    cur.execute(schema)
                except Exception as exc:
                    name = type(exc).__name__
                    # Aceitar InsufficientPrivilege (codigo SQLSTATE 42501)
                    # ou ProgrammingError vindo de ALTER TABLE em tabela alheia.
                    # Outras falhas (sintaxe, conexao, etc) propagam.
                    if 'InsufficientPrivilege' not in name and \
                       'permission denied' not in str(exc).lower():
                        raise
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "schema_postgres.sql parcialmente aplicado: %s. "
                        "Esperado se Ansible nao rodou ainda (DB clean-room). "
                        "Rode `make -f ark/Makefile ansible-apply` pra aplicar "
                        "ALTER OWNER + GRANTs definitivos. Tabelas devem existir.",
                        exc,
                    )

    @contextmanager
    def _conn(self) -> Iterator:
        with self._pool.connection() as conn:
            yield conn

    # sites
    def criar_site(self, slug, nome, ambiente, dominios, plano="free", bucket_name=None):
        site_id = str(uuid.uuid4())
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sites (id, slug, nome, ambiente, plano, bucket_name) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (site_id, slug, nome, ambiente, plano, bucket_name),
            )
            for dom in dominios:
                cur.execute(
                    "INSERT INTO site_dominios (site_id, dominio) VALUES (%s, %s)",
                    (site_id, dom.rstrip("/")),
                )
            cur.execute("INSERT INTO quotas (site_id) VALUES (%s)", (site_id,))
        return Site(id=site_id, slug=slug, nome=nome, ambiente=ambiente, plano=plano,
                    status="ativo", bucket_name=bucket_name)

    def obter_site(self, site_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM sites WHERE id = %s", (site_id,))
            row = cur.fetchone()
        return _dict_to_site(row) if row else None

    def obter_site_por_slug(self, slug):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
            row = cur.fetchone()
        return _dict_to_site(row) if row else None

    def obter_site_por_bucket(self, bucket_name):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM sites WHERE bucket_name = %s", (bucket_name,))
            row = cur.fetchone()
        return _dict_to_site(row) if row else None

    def listar_sites(self):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM sites ORDER BY criado_em")
            return [_dict_to_site(r) for r in cur.fetchall()]

    def atualizar_status_site(self, site_id, status):
        if status not in ("ativo", "suspenso", "bloqueado"):
            raise ValueError(f"status invalido: {status}")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE sites SET status = %s, atualizado_em = NOW() WHERE id = %s",
                (status, site_id),
            )

    def atualizar_plano(self, site_id, plano):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE sites SET plano = %s, atualizado_em = NOW() WHERE id = %s",
                (plano, site_id),
            )

    def definir_bucket_name(self, site_id, bucket_name):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE sites SET bucket_name = %s, atualizado_em = NOW() WHERE id = %s",
                (bucket_name, site_id),
            )

    # dominios
    def listar_dominios(self, site_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT dominio FROM site_dominios WHERE site_id = %s", (site_id,))
            return [r["dominio"] for r in cur.fetchall()]

    def adicionar_dominio(self, site_id, dominio):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO site_dominios (site_id, dominio) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (site_id, dominio.rstrip("/")),
            )

    def remover_dominio(self, site_id, dominio):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM site_dominios WHERE site_id = %s AND dominio = %s",
                (site_id, dominio.rstrip("/")),
            )

    def origin_permitido(self, site_id, origin):
        if not origin:
            return False
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM site_dominios WHERE site_id = %s AND dominio = %s LIMIT 1",
                (site_id, origin.rstrip("/")),
            )
            return cur.fetchone() is not None

    def dominio_existe(self, dominio):
        if not dominio:
            return False
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM site_dominios WHERE dominio = %s LIMIT 1",
                (dominio.rstrip("/"),),
            )
            return cur.fetchone() is not None

    # publishable
    def criar_publishable_key(self, site_id, ambiente, nome=None):
        key_id = uuid.uuid4().hex[:12]
        valor = f"pk_{ambiente}_{secrets.token_urlsafe(32)}"
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO publishable_keys (key_id, site_id, valor, nome) VALUES (%s, %s, %s, %s)",
                (key_id, site_id, valor, nome),
            )
        return PublishableKey(key_id=key_id, site_id=site_id, valor=valor, nome=nome, revogada=False), valor

    def obter_publishable_por_valor(self, valor):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM publishable_keys WHERE valor = %s", (valor,))
            row = cur.fetchone()
        return _dict_to_key(row) if row else None

    def listar_publishable_keys(self, site_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM publishable_keys WHERE site_id = %s ORDER BY criado_em",
                (site_id,),
            )
            return [_dict_to_key(r) for r in cur.fetchall()]

    def revogar_publishable_key(self, key_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE publishable_keys SET revogado_em = NOW() WHERE key_id = %s",
                (key_id,),
            )

    # quotas
    def obter_quota(self, site_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM quotas WHERE site_id = %s", (site_id,))
            row = cur.fetchone()
        if not row:
            return None
        return Quota(
            site_id=str(row["site_id"]),
            eventos_por_minuto=row["eventos_por_minuto"],
            eventos_por_dia=row["eventos_por_dia"],
            emissoes_jwt_por_minuto=row["emissoes_jwt_por_minuto"],
            retencao_dias=row["retencao_dias"],
        )

    def atualizar_quota(self, site_id, *, eventos_por_minuto=None, eventos_por_dia=None,
                        emissoes_jwt_por_minuto=None, retencao_dias=None):
        campos = {}
        if eventos_por_minuto is not None: campos["eventos_por_minuto"] = eventos_por_minuto
        if eventos_por_dia is not None: campos["eventos_por_dia"] = eventos_por_dia
        if emissoes_jwt_por_minuto is not None: campos["emissoes_jwt_por_minuto"] = emissoes_jwt_por_minuto
        if retencao_dias is not None: campos["retencao_dias"] = retencao_dias
        if not campos:
            return
        sets = ", ".join(f"{k} = %s" for k in campos)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE quotas SET {sets} WHERE site_id = %s",
                        list(campos.values()) + [site_id])

    # consumo
    def consumo_em_dia(self, site_id: str, dia: date) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT eventos FROM consumo_diario WHERE site_id = %s AND dia = %s",
                (site_id, dia),
            )
            row = cur.fetchone()
        return int(row["eventos"]) if row else 0

    def consumo_hoje(self, site_id):
        return self.consumo_em_dia(site_id, datetime.now(timezone.utc).date())

    def incrementar_consumo(self, site_id, eventos=1):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO consumo_diario (site_id, dia, eventos)
                VALUES (%s, CURRENT_DATE, %s)
                ON CONFLICT (site_id, dia) DO UPDATE
                SET eventos = consumo_diario.eventos + EXCLUDED.eventos,
                    atualizado_em = NOW()
                """,
                (site_id, eventos),
            )

    # emissoes
    def registrar_emissao(self, *, site_id, publishable_id, jti, origin, ip):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO emissoes_jwt (site_id, publishable_id, origin, ip, jti)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (site_id, publishable_id, origin, ip, jti),
            )

    def contar_emissoes_recentes(self, publishable_id, janela_segundos=60):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total FROM emissoes_jwt
                WHERE publishable_id = %s AND emitido_em >= NOW() - MAKE_INTERVAL(secs => %s)
                """,
                (publishable_id, janela_segundos),
            )
            row = cur.fetchone()
        return int(row["total"]) if row else 0

    def limpar_emissoes_antigas(self, dias=7):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM emissoes_jwt WHERE emitido_em < NOW() - MAKE_INTERVAL(days => %s)",
                (dias,),
            )
            return cur.rowcount or 0

    # idempotencia stripe
    def marcar_evento_stripe_processado(self, event_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO stripe_eventos_processados (event_id) VALUES (%s) "
                "ON CONFLICT (event_id) DO NOTHING",
                (event_id,),
            )
            return (cur.rowcount or 0) > 0

    # revogacao embed jwt
    def jti_embed_esta_revogado(self, jti):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM embed_jwt_revogados WHERE jti = %s LIMIT 1",
                (jti,),
            )
            return cur.fetchone() is not None

    def revogar_jti_embed(self, jti, *, motivo=None):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO embed_jwt_revogados (jti, motivo) VALUES (%s, %s) "
                "ON CONFLICT (jti) DO NOTHING",
                (jti, motivo),
            )

    def purgar_embed_jwt_revogados_antigos(self, retencao_horas=48):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM embed_jwt_revogados "
                "WHERE revogado_em < NOW() - (%s || ' hours')::interval",
                (str(int(retencao_horas)),),
            )
            return cur.rowcount or 0


def _dict_row():
    """Row factory de psycopg3 que devolve dicts (compat com _dict_to_*)."""
    from psycopg.rows import dict_row
    return dict_row


def _dict_to_site(row: dict) -> Site:
    return Site(
        id=str(row["id"]),
        slug=row["slug"],
        nome=row["nome"],
        ambiente=row["ambiente"],
        plano=row["plano"],
        status=row["status"],
        bucket_name=row.get("bucket_name"),
    )


def _dict_to_key(row: dict) -> PublishableKey:
    return PublishableKey(
        key_id=row["key_id"],
        site_id=str(row["site_id"]),
        valor=row["valor"],
        nome=row["nome"],
        revogada=row["revogado_em"] is not None,
    )


# ======================================================================
#                            factory + singleton
# ======================================================================


def criar_tenants_repo(url: str) -> TenantsRepo:
    """Cria a implementacao certa a partir do `url`.

      - `postgresql://...` ou `postgres://...`  -> PostgresTenantsRepo
      - `sqlite:///path`                         -> SqliteTenantsRepo
      - outro valor (path absoluto)              -> SqliteTenantsRepo (compat)
    """
    if url.startswith(("postgresql://", "postgres://")):
        return PostgresTenantsRepo(url)
    if url.startswith("sqlite:///"):
        return SqliteTenantsRepo(url[len("sqlite:///"):])
    # path nu = sqlite (backward compat)
    return SqliteTenantsRepo(url)


_repo_instance: Optional[TenantsRepo] = None
_repo_lock = threading.Lock()


def obter_repo(url: Optional[str] = None) -> TenantsRepo:
    """Singleton. Primeiro chamador define a URL/path."""
    global _repo_instance
    with _repo_lock:
        if _repo_instance is None:
            if url is None:
                raise RuntimeError("TenantsRepo nao inicializado; passe url/path na primeira chamada")
            _repo_instance = criar_tenants_repo(url)
        return _repo_instance


def resetar_repo() -> None:
    """Apenas para testes."""
    global _repo_instance
    with _repo_lock:
        _repo_instance = None


# Aliases de compat — codigo antigo que importava `TenantsRepo` como classe continua funcionando.
# Apontam para SqliteTenantsRepo para manter comportamento default.
# (Produtivo e prefira `criar_tenants_repo`.)
_TenantsRepo_legacy = SqliteTenantsRepo
